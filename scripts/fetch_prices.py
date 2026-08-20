import json
import os
import re
from datetime import datetime

# ── 設定 ──────────────────────────────────────────────────
TWEETS_FILE = "data/tweets.json"
OUTPUT_FILE  = "data/prices.json"
MAX_TICKERS  = 50  # 只抓出現頻率最高的前 50 個標的

# 與 build_html.py 相同的黑名單
BLACKLIST = {"USD", "CAD", "EUR", "ATH", "CEO", "AI", "FOMC", "FED", "CPI", "GDP", "DD", "EOD", "YOLO"}

# ── 工具函數 ──────────────────────────────────────────────
def extract_tickers_from_text(text):
    """從推文文字提取 ticker（與 build_html.py 邏輯相同）"""
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Z]{1,5})\b", text.upper())
    return [t for t in set(matches) if t not in BLACKLIST]

def get_top_tickers(tweets_file):
    """讀取 tweets.json，統計各 ticker 出現次數，回傳 top N"""
    if not os.path.exists(tweets_file):
        print(f"❌ 找不到 {tweets_file}")
        return []
    try:
        with open(tweets_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 讀取推文失敗: {e}")
        return []

    # 相容多種 JSON 結構
    if isinstance(data, list):
        tweets = data
    elif isinstance(data, dict):
        tweets = data.get("tweets", data.get("data", list(data.values())))
    else:
        return []

    ticker_counts = {}
    for item in tweets:
        text = ""
        for k in ["text", "rawContent", "full_text", "content"]:
            if k in item and item[k]:
                text = str(item[k])
                break
        for ticker in extract_tickers_from_text(text):
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

    sorted_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
    top = [t for t, _ in sorted_tickers[:MAX_TICKERS]]
    print(f"🔍 找到 {len(ticker_counts)} 個 ticker，抓取前 {len(top)} 個")
    return top

def fetch_price_data(tickers):
    """使用 yfinance 批次抓取各 ticker 股價快照"""
    try:
        import yfinance as yf
    except ImportError:
        print("❌ yfinance 未安裝")
        return {}

    prices = {}
    print(f"📊 開始抓取 {len(tickers)} 個標的...")

    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).fast_info

            price       = getattr(info, "last_price",     None)
            prev_close  = getattr(info, "previous_close", None)
            week52_high = getattr(info, "year_high",      None)
            week52_low  = getattr(info, "year_low",       None)
            volume      = getattr(info, "last_volume",    None)

            # 無有效股價 → 略過（非美股 ticker 常見）
            if price is None or price <= 0:
                print(f"  ⚠️  {ticker}: 無有效股價，略過")
                continue

            change     = round(float(price) - float(prev_close), 2) if prev_close else None
            change_pct = round(change / float(prev_close) * 100, 2) if change and prev_close else None

            prices[ticker] = {
                "price":       round(float(price), 2),
                "prev_close":  round(float(prev_close), 2) if prev_close else None,
                "change":      change,
                "change_pct":  change_pct,
                "week52_high": round(float(week52_high), 2) if week52_high else None,
                "week52_low":  round(float(week52_low),  2) if week52_low  else None,
                "volume":      int(volume) if volume else None,
                "updated_at":  datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            }
            sign = "+" if (change or 0) >= 0 else ""
            print(f"  ✅ {ticker}: ${price:.2f}  {sign}{change_pct:.2f}%")

        except Exception as e:
            print(f"  ❌ {ticker}: {e}")
            continue

    return prices

# ── 主流程 ────────────────────────────────────────────────
def main():
    print("=== 股價資料抓取腳本 ===")

    tickers = get_top_tickers(TWEETS_FILE)
    if not tickers:
        print("⚠️  沒有找到任何 ticker，輸出空檔案")
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return

    prices = fetch_price_data(tickers)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(prices, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 股價資料輸出至 {OUTPUT_FILE}（共 {len(prices)} 個標的）")

if __name__ == "__main__":
    main()
