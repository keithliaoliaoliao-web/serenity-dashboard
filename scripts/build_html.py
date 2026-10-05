"""把推文、情緒分析、論點庫與股價整合成 docs/index.html。
網頁樣板在同資料夾的 dashboard_template.html（和程式分開，之後改畫面不會踩到 Python 語法）。"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

from common import (TARGET_HANDLE, log, extract_tickers, snowflake_to_iso, tweet_id_of,
                    tweet_text_of, load_tweet_list, load_sentiment_cache, load_json,
                    save_json, normalize_sentiment)

TWEETS_FILE = "data/tweets.json"
ALT_TWEETS_FILE = "data/aleabitoreddit_tweets.json"
CACHE_FILE = "data/sentiment_cache.json"
THESIS_FILE = "data/thesis_cache.json"
STATUS_FILE = "data/status.json"
QUOTES_CACHE_FILE = "data/stock_quotes_cache.json"
OUTPUT_HTML = "docs/index.html"
TEMPLATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_template.html")

REMOTE_TWEETS_URL = "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json"
CDN_TWEETS_URL = "https://cdn.jsdelivr.net/gh/yan-labs/serenity-aleabitoreddit@main/data/aleabitoreddit_tweets.json"

HISTORY_PERIOD = "2y"      # 股價歷史長度（1 年內逐日，更早的改為每週一點以控制檔案大小）
DOWNLOAD_CHUNK = 40        # 每批下載幾檔，避免被限流
MAX_TARGETS = 350

TICKER_FETCH_MAP = {
    "SIVE": "SIVE.ST", "SOI": "SOI.PA", "AIXA": "AIXA.DE", "IQE": "IQE.L",
    "XFAB": "XFAB.PA", "LPK": "LPK.DE", "ALRIB": "ALRIB.PA", "DOWA": "5714.T", "BITF": "BITF",
}
TRADINGVIEW_MAP = {
    "SIVE": "OMXSTO:SIVE", "SOI": "EURONEXT:SOI", "AIXA": "XETR:AIXA", "IQE": "LSE:IQE",
    "XFAB": "EURONEXT:XFAB", "LPK": "XETR:LPK", "ALRIB": "EURONEXT:ALRIB",
    "DOWA": "TSE:5714", "BITF": "NASDAQ:BITF",
}
SECTOR_MAPPING = {
    "生技與醫療製藥": ["HIMS", "MRNA", "JNJ", "TEM", "LLY", "NVO", "ISRG", "CRSP", "VRTX", "AMGN",
                       "BNTX", "PFE", "ABBV", "BIIB", "REGN", "ILMN", "EXAS", "DNA", "UNH"],
    "半導體設備與封測": ["AMAT", "ASML", "LRCX", "KLAC", "AEHR", "AMKR", "ONTO", "CAMT", "TER", "ICHR",
                         "FORM", "COHR", "ACLS", "UCTT", "KLIC"],
    "AI 算力與高速互連": ["NVDA", "AMD", "AVGO", "MRVL", "ARM", "ALAB", "INTC", "TSM", "QCOM", "CRDO",
                          "POET", "MTSI", "AOSL", "DIOD", "SMCI", "TSEM", "INDI", "LSCC", "AMBA"],
    "光通訊與雷射網通": ["AAOI", "LITE", "COHR", "POET", "CIEN", "FN", "SIVE", "GLW", "CBRS", "ACIA",
                         "HLIT", "EXTR", "CALX", "INFN"],
    "記憶體與儲存設備": ["SNDK", "MU", "WDC", "PSTG", "STX", "NTAP", "SKHY", "YMTC"],
    "AI 算力中心與採礦": ["NBIS", "APLD", "CRWV", "HUT", "IREN", "CIFR", "CLSK", "MARA", "RIOT", "CORZ",
                          "WULF", "BITF", "SDIG", "CRCL"],
    "太空科技與國防": ["RKLB", "RCAT", "ASTS", "AVAV", "KTOS", "LMT", "RTX", "PL", "NOC", "GD",
                       "BA", "HII", "LDOS", "AXON"],
    "潔淨能源與電力設備": ["BE", "SMR", "OKLO", "LEU", "UUUU", "VRT", "CEG", "FLNC", "GEV", "AEP",
                           "NEE", "CCJ", "ENPH", "SEDG", "FSLR", "AES", "VST"],
    "雲端巨頭與平台軟體": ["AMZN", "MSFT", "GOOGL", "META", "AAPL", "PLTR", "SNOW", "NOW", "CRWD", "DDOG",
                           "NET", "PATH", "MDB", "ORCL", "CRM", "PANW", "ZS", "ADBE", "HOOD", "PYPL", "RDDT"],
    "指數與主題科技 ETF": ["ARKK", "QQQ", "SPY", "SMH", "SOXX", "XBI", "IWM", "ARKW", "ARKG", "IBIT"],
}
ETF_SYMBOLS = set(SECTOR_MAPPING["指數與主題科技 ETF"])


def resolve_sector(ticker, yf_info=None):
    sym = ticker.upper().strip()
    for name, symbols in SECTOR_MAPPING.items():
        if sym in symbols:
            return name
    if yf_info and isinstance(yf_info, dict):
        ind = str(yf_info.get("industry", "")).lower()
        rules = [
            ("生技與醫療製藥", ["biotechnology", "drug", "pharmaceutical", "healthcare", "medical"]),
            ("半導體設備與封測", ["semiconductor equipment", "semiconductor - equipment", "packaging"]),
            ("AI 算力與高速互連", ["semiconductor", "integrated circuits"]),
            ("光通訊與雷射網通", ["communication equipment", "fiber", "optical", "telecom"]),
            ("記憶體與儲存設備", ["computer hardware", "data storage", "memory"]),
            ("太空科技與國防", ["aerospace", "defense"]),
            ("潔淨能源與電力設備", ["utilities", "uranium", "nuclear", "solar", "renewable", "electrical"]),
            ("雲端巨頭與平台軟體", ["software", "internet", "cloud", "information technology"]),
        ]
        for name, words in rules:
            if any(w in ind for w in words):
                return name
    return "其他科技 / 綜合"


# ---------------------------------------------------------------- 推文整理
def load_tweets():
    tweets = load_tweet_list(TWEETS_FILE) or load_tweet_list(ALT_TWEETS_FILE)
    if tweets:
        return tweets
    log("🌐 本地推文為空，從備援來源拉取...")
    for url in (REMOTE_TWEETS_URL, CDN_TWEETS_URL):
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            if res.status_code == 200:
                data = res.json()
                tweets = data if isinstance(data, list) else list(data.values())
                if tweets:
                    save_json(TWEETS_FILE, tweets)
                    log(f"✅ 拉取 {len(tweets)} 則並存檔")
                    return tweets
        except Exception as e:
            log(f"⚠️ 備援來源失敗: {e}")
    return []


def parse_date(item, tweet_id):
    """回傳 (顯示時間, 月份, 日期, ISO)，一律以推文 ID 推算的 UTC 時間為準。"""
    iso = snowflake_to_iso(tweet_id)
    if iso:
        return iso[:10] + " " + iso[11:16], iso[:7], iso[:10], iso
    raw = str(item.get("created_at") or item.get("date") or "")
    return (raw[:16] or "未知時間"), (raw[:7] or "未知月份"), (raw[:10] or "未知日期"), ""


def extract_metrics(item):
    containers = [item] + [item[k] for k in ("public_metrics", "metrics", "stats", "legacy")
                           if isinstance(item.get(k), dict)]

    def pick(keys):
        for c in containers:
            for k in keys:
                v = c.get(k)
                if isinstance(v, dict):
                    v = v.get("count")
                if v is not None and str(v).strip().isdigit() and int(str(v).strip()) > 0:
                    return int(str(v).strip())
        return 0

    return (pick(["favorite_count", "likeCount", "likes", "like_count", "favoriteCount"]),
            pick(["retweet_count", "retweetCount", "retweets", "reposts", "repost_count"]),
            pick(["views", "view_count", "viewCount", "impression_count", "impressions"]))


def clean_tweet_data(raw_tweets, sentiment_cache):
    cleaned, ticker_counts = [], {}
    for item in raw_tweets:
        if not isinstance(item, dict):
            continue
        tweet_id, text = tweet_id_of(item), tweet_text_of(item)
        if not text:
            continue
        date_str, month_str, day_str, iso = parse_date(item, tweet_id)
        tickers = extract_tickers(text)
        likes, retweets, views = extract_metrics(item)
        for t in tickers:
            ticker_counts[t] = ticker_counts.get(t, 0) + 1

        ai = sentiment_cache.get(tweet_id) if tweet_id else None
        sentiment, summary, translation, risk, stances = "Neutral", "", "", "", {}
        if isinstance(ai, dict):
            sentiment = normalize_sentiment(ai.get("sentiment"))
            summary = ai.get("summary", "") or ai.get("summary_zh", "") or ""
            translation = ai.get("translation_zh", "") or ai.get("chinese", "") or ""
            risk = str(ai.get("risk") or "")
            if isinstance(ai.get("stances"), dict):
                stances = {str(k).upper(): normalize_sentiment(v) for k, v in ai["stances"].items()}

        url = str(item.get("url") or item.get("permanentUrl") or item.get("link") or "")
        if not url.startswith(("https://", "http://")):
            url = f"https://twitter.com/{TARGET_HANDLE}/status/{tweet_id}" if tweet_id else "#"

        cleaned.append({
            "id": tweet_id, "text": text, "date": date_str, "day": day_str, "month": month_str,
            "iso_date": iso, "tickers": tickers, "likes": likes, "retweets": retweets, "views": views,
            "sentiment": sentiment, "stances": stances, "risk": risk, "summary": summary,
            "translation_zh": translation, "is_analyzed": bool(summary or translation), "url": url,
        })

    cleaned.sort(key=lambda x: str(x.get("iso_date") or x.get("date") or ""), reverse=True)
    recent_tickers = []
    for tw in cleaned[:60]:
        for t in tw["tickers"]:
            if t not in recent_tickers:
                recent_tickers.append(t)
    return cleaned, ticker_counts, recent_tickers


# ---------------------------------------------------------------- 股價
def compress_history(history):
    """1 年內保留逐日；更早的每週只留最後一天，控制網頁檔案大小。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=370)).strftime("%Y-%m-%d")
    old = [h for h in history if h["d"] < cutoff]
    recent = [h for h in history if h["d"] >= cutoff]
    weekly = {}
    for h in old:
        y, w, _ = datetime.strptime(h["d"], "%Y-%m-%d").isocalendar()
        weekly[(y, w)] = h
    return list(weekly.values()) + recent


def series_to_history(series):
    out = []
    for ts, c in series.dropna().items():
        out.append({"d": ts.strftime("%Y-%m-%d"), "c": round(float(c), 2)})
    return out


def download_histories(symbols):
    result = {}
    for i in range(0, len(symbols), DOWNLOAD_CHUNK):
        chunk = symbols[i:i + DOWNLOAD_CHUNK]
        try:
            df = yf.download(chunk, period=HISTORY_PERIOD, interval="1d", group_by="ticker",
                             threads=True, progress=False)
        except Exception as e:
            log(f"  ⚠️ 日 K 批次下載失敗 ({chunk[0]}…): {e}")
            continue
        if df is None or df.empty:
            continue
        multi = getattr(df.columns, "nlevels", 1) > 1
        top = set(df.columns.get_level_values(0)) if multi else set()
        for sym in chunk:
            try:
                if multi:
                    sub = df[sym] if sym in top else None
                else:
                    sub = df if len(chunk) == 1 else None
                if sub is not None and "Close" in sub:
                    result[sym] = series_to_history(sub["Close"])
            except Exception as e:
                log(f"  ⚠️ {sym} 日 K 解析失敗: {e}")
        time.sleep(1.5)
    return result


def fetch_one(symbol, fetch_symbol, history):
    """取得單一標的行情與估值，回傳 (quote 或 None, sector, currency)。"""
    price = prev = high52 = low52 = volume = mcap = None
    fwd_pe = ttm_pe = ps = growth = None
    earnings = None
    currency, info = "USD", {}
    try:
        tk = yf.Ticker(fetch_symbol)
        fast = getattr(tk, "fast_info", None)
        price = getattr(fast, "last_price", None) or getattr(fast, "regular_market_price", None)
        prev = getattr(fast, "previous_close", None)
        high52 = getattr(fast, "year_high", None)
        low52 = getattr(fast, "year_low", None)
        volume = getattr(fast, "last_volume", None) or getattr(fast, "regular_market_volume", None)
        mcap = getattr(fast, "market_cap", None)
        currency = getattr(fast, "currency", "USD") or "USD"

        if not history:
            try:
                history = compress_history(series_to_history(tk.history(period=HISTORY_PERIOD)["Close"]))
            except Exception:
                pass

        if symbol == "BITF" and (price is None or float(price) <= 0):   # 雙重掛牌回退
            try:
                alt = yf.Ticker("BITF.TO")
                af = getattr(alt, "fast_info", None)
                price = getattr(af, "last_price", None)
                if price:
                    prev = getattr(af, "previous_close", None)
                    currency = getattr(af, "currency", "CAD") or "CAD"
                    if not history:
                        history = compress_history(series_to_history(alt.history(period=HISTORY_PERIOD)["Close"]))
            except Exception:
                pass

        try:
            info = tk.info or {}
        except Exception:
            info = {}
        price = price or info.get("currentPrice") or info.get("regularMarketPrice")
        prev = prev or info.get("regularMarketPreviousClose") or info.get("previousClose")
        high52 = high52 or info.get("fiftyTwoWeekHigh")
        low52 = low52 or info.get("fiftyTwoWeekLow")
        volume = volume or info.get("volume")
        mcap = mcap or info.get("marketCap")
        if currency == "USD" and info.get("currency"):
            currency = info["currency"]
        fwd_pe, ttm_pe = info.get("forwardPE"), info.get("trailingPE")
        ps, growth = info.get("priceToSalesTrailing12Months"), info.get("revenueGrowth")

        if symbol in ETF_SYMBOLS:
            earnings = "指數 ETF (無財報)"
        else:
            try:
                cal = tk.calendar
                if isinstance(cal, dict) and cal.get("Earnings Date"):
                    earnings = str(cal["Earnings Date"][0])[:10]
            except Exception:
                pass
    except Exception as e:
        log(f"  ⚠️ {symbol} 行情抓取異常: {e}")

    if history:   # 日 K 回填，確保現價與 52 週水位一定有值
        if not price or float(price) <= 0:
            price = history[-1]["c"]
        if (not prev or float(prev) <= 0) and len(history) >= 2:
            prev = history[-2]["c"]
        one_year = [h["c"] for h in history if h["d"] >= (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")] or [h["c"] for h in history]
        high52 = high52 or max(one_year)
        low52 = low52 or min(one_year)
        history = compress_history(history) if len(history) > 400 else history

    sector = resolve_sector(symbol, info)
    if not price or float(price) <= 0:
        return None, sector, currency, history

    change = (price - prev) if prev else 0.0
    pct = (change / prev * 100) if prev else 0.0
    quote = {
        "price": round(float(price), 2),
        "prevClose": round(float(prev), 2) if prev else round(float(price), 2),
        "change": round(float(change), 2), "changePct": round(float(pct), 2),
        "high52": round(float(high52), 2) if high52 else None,
        "low52": round(float(low52), 2) if low52 else None,
        "volume": int(volume) if volume else 0,
        "marketCap": int(mcap) if mcap else None,
        "forwardPE": round(float(fwd_pe), 2) if fwd_pe else None,
        "trailingPE": round(float(ttm_pe), 2) if ttm_pe else None,
        "priceToSales": round(float(ps), 2) if ps else None,
        "revenueGrowth": round(float(growth) * 100, 1) if growth else None,
        "earningsDate": earnings, "sector": sector, "currency": currency,
        "asOf": history[-1]["d"] if history else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "history": history,
    }
    return quote, sector, currency, history


def fetch_stock_quotes_and_fundamentals(tickers):
    log(f"📈 擷取 {len(tickers)} 個標的的行情、估值與 {HISTORY_PERIOD} 日 K...")
    quotes = load_json(QUOTES_CACHE_FILE, {})
    quotes = quotes if isinstance(quotes, dict) else {}

    fetch_map = {s: TICKER_FETCH_MAP.get(s, s) for s in tickers}
    histories = download_histories(list(dict.fromkeys(fetch_map.values())))

    for symbol in tickers:
        fetch_symbol = fetch_map[symbol]
        hist = histories.get(fetch_symbol, [])
        hist = compress_history(hist) if hist else []
        quote, sector, currency, hist = fetch_one(symbol, fetch_symbol, hist)
        if quote:
            quotes[symbol] = quote
            log(f"  ✅ ${symbol}: {quote['currency']} {quote['price']:.2f} ({quote['changePct']:+.2f}%) | 日K {len(quote['history'])} 筆")
        elif symbol in quotes and quotes[symbol].get("history"):
            log(f"  🔄 ${symbol}: 沿用快取（資料日 {quotes[symbol].get('asOf', '未知')}）")
        else:
            quotes[symbol] = {"sector": sector, "currency": currency, "history": hist or []}

    save_json(QUOTES_CACHE_FILE, quotes)
    return quotes


# ---------------------------------------------------------------- 輸出
def safe_json(obj):
    """轉成可安全塞進 <script> 的 JSON（避免推文內容含 </script> 把頁面弄壞）。"""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def generate_html(tweets, stock_quotes, thesis, status):
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    build_info = {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_tweet_at": tweets[0]["iso_date"] if tweets else None,
        "status": status if isinstance(status, dict) else {},
    }
    replacements = {
        "__TWEETS_DATA__": safe_json(tweets),
        "__STOCK_QUOTES__": safe_json(stock_quotes),
        "__SECTOR_MAPPING__": safe_json(SECTOR_MAPPING),
        "__TRADINGVIEW_MAP__": safe_json(TRADINGVIEW_MAP),
        "__THESIS_DATA__": safe_json(thesis if isinstance(thesis, dict) else {}),
        "__BUILD_INFO__": safe_json(build_info),
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"✅ 儀表板已產出：{OUTPUT_HTML}")


def main():
    raw = load_tweets()
    cache = load_sentiment_cache(CACHE_FILE)
    tweets, counts, recent = clean_tweet_data(raw, cache)
    log(f"📦 原始推文 {len(raw)} 則｜有效 {len(tweets)} 則")

    sector_symbols = [s for sub in SECTOR_MAPPING.values() for s in sub]
    by_mentions = [t for t, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)]
    targets = list(dict.fromkeys(sector_symbols + recent + by_mentions))[:MAX_TARGETS]
    log(f"🎯 本次抓取市場數據：{len(targets)} 檔")

    quotes = fetch_stock_quotes_and_fundamentals(targets)
    generate_html(tweets, quotes, load_json(THESIS_FILE, {}), load_json(STATUS_FILE, {}))


if __name__ == "__main__":
    main()
