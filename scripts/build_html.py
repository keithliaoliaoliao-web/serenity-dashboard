import json
import os
import re
from datetime import datetime
import yfinance as yf

TWEETS_FILE = "data/tweets.json"
CACHE_FILE = "data/sentiment_cache.json"
OUTPUT_HTML = "docs/index.html"

def load_tweets(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for key in ["tweets", "data", "statuses", "results"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return list(data.values())
            return []
    except Exception as e:
        print(f"⚠️ 讀取推文檔案失敗 ({filepath}): {e}")
        return []

def load_cache(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                cache_dict = {}
                for item in data:
                    if isinstance(item, dict):
                        t_id = str(item.get("id") or item.get("tweet_id") or "")
                        if t_id:
                            cache_dict[t_id] = item
                return cache_dict
            return {}
    except Exception as e:
        print(f"⚠️ 讀取快取檔案失敗 ({filepath}): {e}")
        return {}

def extract_tickers(text):
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Z]{1,5})\b", text.upper())
    blacklist = {"USD", "CAD", "EUR", "ATH", "CEO", "AI", "FOMC", "FED", "CPI", "GDP", "DD", "EOD", "YOLO"}
    return sorted(list(set(t for t in matches if t not in blacklist)))

def extract_tweet_id(item):
    for k in ["id", "id_str", "tweet_id", "tweetId", "rest_id", "conversation_id"]:
        if k in item and item[k]:
            return str(item[k]).strip()
    url = item.get("url") or item.get("permanentUrl") or item.get("link") or ""
    if url:
        m = re.search(r"status/(\d+)", str(url))
        if m:
            return m.group(1).strip()
    return ""

def extract_tweet_text(item):
    for k in ["text", "rawContent", "full_text", "content", "tweet", "body", "message"]:
        if k in item and item[k]:
            return str(item[k])
    legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
    if "full_text" in legacy:
        return str(legacy["full_text"])
    return ""

def parse_date(item):
    raw_date = None
    for k in ["date", "created_at", "createdAt", "timestamp", "datetime", "time"]:
        if k in item and item[k]:
            raw_date = item[k]
            break
    if not raw_date:
        legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
        raw_date = legacy.get("created_at")

    if not raw_date:
        return "未知時間", "未知月份"

    if isinstance(raw_date, (int, float)):
        try:
            val = float(raw_date)
            dt = datetime.fromtimestamp(val / 1000.0 if val > 1e11 else val)
            return dt.strftime("%Y-%m-%d %H:%M"), dt.strftime("%Y-%m")
        except Exception:
            pass

    s = str(raw_date).strip()
    if s.isdigit():
        try:
            val = float(s)
            dt = datetime.fromtimestamp(val / 1000.0 if val > 1e11 else val)
            return dt.strftime("%Y-%m-%d %H:%M"), dt.strftime("%Y-%m")
        except Exception:
            pass

    try:
        if "T" in s or "+" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M"), dt.strftime("%Y-%m")
    except Exception:
        pass

    try:
        if len(s.split()) >= 6:
            dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
            return dt.strftime("%Y-%m-%d %H:%M"), dt.strftime("%Y-%m")
    except Exception:
        pass

    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mth, d = m.groups()
        return f"{int(y):04d}-{int(mth):02d}-{int(d):02d}", f"{int(y):04d}-{int(mth):02d}"

    return s, "未知月份"

def extract_metrics(item):
    likes, retweets, views = 0, 0, 0
    containers = [item]
    for sub in ["public_metrics", "metrics", "stats", "legacy"]:
        val = item.get(sub)
        if isinstance(val, dict):
            containers.append(val)

    def get_num(d, keys):
        if not isinstance(d, dict):
            return None
        for k in keys:
            if k in d and d[k] is not None:
                val_str = str(d[k]).strip()
                if val_str.isdigit():
                    return int(val_str)
        return None

    for c in containers:
        if not isinstance(c, dict):
            continue
        if likes == 0:
            val = get_num(c, ["likeCount", "likes", "like_count", "favorite_count", "favorites", "favoriteCount", "favs"])
            if val is not None:
                likes = val
        if retweets == 0:
            val = get_num(c, ["retweetCount", "retweets", "retweet_count", "reposts", "repost_count"])
            if val is not None:
                retweets = val
        if views == 0:
            val = get_num(c, ["viewCount", "views", "view_count", "impression_count", "impressions"])
            if val is not None:
                views = val

    return likes, retweets, views

def clean_tweet_data(raw_tweets, sentiment_cache):
    if isinstance(sentiment_cache, list):
        cache_dict = {}
        for item in sentiment_cache:
            if isinstance(item, dict):
                t_id = str(item.get("id") or item.get("tweet_id") or "")
                if t_id:
                    cache_dict[t_id] = item
        sentiment_cache = cache_dict
    elif not isinstance(sentiment_cache, dict):
        sentiment_cache = {}

    cleaned = []
    ticker_counts = {}

    for item in raw_tweets:
        if not isinstance(item, dict):
            continue

        tweet_id = extract_tweet_id(item)
        text = extract_tweet_text(item)
        if not text:
            continue

        date_str, month_str = parse_date(item)
        tickers = extract_tickers(text)
        likes, retweets, views = extract_metrics(item)

        for t in tickers:
            ticker_counts[t] = ticker_counts.get(t, 0) + 1

        ai_data = sentiment_cache.get(tweet_id) if tweet_id else None
        sentiment = "Neutral"
        summary = ""
        translation_zh = ""

        if ai_data and isinstance(ai_data, dict):
            sentiment = ai_data.get("sentiment", "Neutral")
            summary = ai_data.get("summary", "")
            translation_zh = ai_data.get("translation_zh", "")

        url = item.get("url") or item.get("permanentUrl") or item.get("link")
        if not url and tweet_id:
            url = f"https://twitter.com/i/web/status/{tweet_id}"

        cleaned.append({
            "id": tweet_id,
            "text": text,
            "date": date_str,
            "month": month_str,
            "tickers": tickers,
            "likes": likes,
            "retweets": retweets,
            "views": views,
            "sentiment": sentiment,
            "summary": summary,
            "translation_zh": translation_zh,
            "url": url or "#"
        })

    return cleaned, ticker_counts

def fetch_stock_quotes(tickers):
    """批次獲取美股市場行情數據（股價、漲跌幅、52週高低點、成交量）"""
    print(f"📈 正在擷取 {len(tickers)} 個關注標的的市場行情數據...")
    quotes = {}
    
    for symbol in tickers:
        try:
            ticker_obj = yf.Ticker(symbol)
            fast = getattr(ticker_obj, "fast_info", None)
            
            if fast:
                current_price = getattr(fast, "last_price", None) or getattr(fast, "regular_market_price", None)
                prev_close = getattr(fast, "previous_close", None)
                high_52 = getattr(fast, "year_high", None)
                low_52 = getattr(fast, "year_low", None)
                volume = getattr(fast, "last_volume", None) or getattr(fast, "regular_market_volume", None)
            else:
                info = ticker_obj.info or {}
                current_price = info.get("currentPrice") or info.get("regularMarketPrice")
                prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
                high_52 = info.get("fiftyTwoWeekHigh")
                low_52 = info.get("fiftyTwoWeekLow")
                volume = info.get("regularMarketVolume") or info.get("volume")

            if current_price is not None:
                change = (current_price - prev_close) if prev_close else 0.0
                change_pct = ((change / prev_close) * 100) if prev_close else 0.0

                quotes[symbol] = {
                    "price": round(float(current_price), 2),
                    "prevClose": round(float(prev_close), 2) if prev_close else round(float(current_price), 2),
                    "change": round(float(change), 2),
                    "changePct": round(float(change_pct), 2),
                    "high52": round(float(high_52), 2) if high_52 else None,
                    "low52": round(float(low_52), 2) if low_52 else None,
                    "volume": int(volume) if volume else 0
                }
                print(f"  ✅ ${symbol}: ${current_price:.2f} ({change_pct:+.2f}%)")
        except Exception as e:
            print(f"  ⚠️ 無法取得 ${symbol} 行情: {e}")

    return quotes

def generate_html(tweets, ticker_counts, stock_quotes):
    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    tweets_json_str = json.dumps(tweets, ensure_ascii=False)
    ticker_counts_sorted = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:30]
    top_tickers_json_str = json.dumps(ticker_counts_sorted, ensure_ascii=False)
    stock_quotes_json_str = json.dumps(stock_quotes, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Serenity 美股推文情報與情緒儀表板</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          colors: {{
            brand: {{
              50: '#f0fdfa',
              500: '#14b8a6',
              600: '#0d9488',
              900: '#134e4a',
            }}
          }}
        }}
      }}
    }}
  </script>
  <style>
    body {{ background-color: #0b0f17; }}
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: #0f172a; }}
    ::-webkit-scrollbar-thumb {{ background: #334155; border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: #475569; }}
  </style>
</head>
<body class="text-slate-200 min-h-screen font-sans antialiased selection:bg-teal-500 selection:text-white">

  <!-- 頂部導航 -->
  <header class="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-tr from-teal-500 to-cyan-400 flex items-center justify-center font-bold text-slate-950 text-base shadow-lg shadow-teal-500/20">
          S
        </div>
        <div>
          <h1 class="font-bold text-base sm:text-lg tracking-tight text-white flex items-center gap-2">
            Serenity Dashboard
            <span class="text-[10px] uppercase font-semibold px-2 py-0.5 rounded-full bg-teal-500/10 text-teal-400 border border-teal-500/20">Live</span>
          </h1>
          <p class="text-xs text-slate-400">美股社群情緒與 AI 深度摘要</p>
        </div>
      </div>
      <div class="text-xs text-slate-400 font-mono" id="last-update-time"></div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

    <!-- 概覽數據統計指標 -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4" id="stats-container">
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-medium text-slate-400">推文總數</span>
        <span class="text-2xl font-bold text-white mt-1" id="stat-total">0</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-medium text-emerald-400">看多觀點 (Bullish)</span>
        <span class="text-2xl font-bold text-emerald-400 mt-1" id="stat-bullish">0</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-medium text-rose-400">看空/警戒 (Bearish)</span>
        <span class="text-2xl font-bold text-rose-400 mt-1" id="stat-bearish">0</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-medium text-teal-400">追蹤標的數量</span>
        <span class="text-2xl font-bold text-teal-400 mt-1" id="stat-tickers">0</span>
      </div>
    </div>

    <!-- 熱門標的快速過濾區 -->
    <div class="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-wider">熱門關注標的 ($TICKER)</h2>
        <button id="clear-ticker-btn" onclick="filterByTicker('')" class="text-xs text-teal-400 hover:underline hidden">清除標的篩選</button>
      </div>
      <div class="flex flex-wrap gap-1.5" id="top-tickers-bar"></div>
    </div>

    <!-- 個股即時行情專區 (Stock Quote Card) -->
    <div id="stock-quote-section" class="bg-gradient-to-r from-slate-900/90 via-slate-900/70 to-slate-900/90 border border-slate-700/80 rounded-xl p-5 shadow-lg relative overflow-hidden hidden">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        
        <!-- 左側：標的與價格、漲跌幅 -->
        <div class="flex items-center gap-4">
          <div class="px-3 py-2 bg-slate-800 rounded-lg border border-slate-700 font-mono font-bold text-xl text-teal-400" id="quote-ticker-name">
            $TICKER
          </div>
          <div>
            <div class="flex items-baseline gap-2">
              <span class="text-3xl font-bold font-mono text-white" id="quote-price">$0.00</span>
              <span class="text-xs text-slate-400">USD</span>
            </div>
            <div class="flex items-center gap-2 mt-0.5 text-sm font-semibold font-mono" id="quote-change-container">
              <span id="quote-change">$0.00</span>
              <span id="quote-change-pct">(0.00%)</span>
              <span class="text-xs font-normal text-slate-400">相對前一日收盤</span>
            </div>
          </div>
        </div>

        <!-- 右側：52 週高低點與成交量 -->
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-4 border-t md:border-t-0 md:border-l border-slate-800 pt-3 md:pt-0 md:pl-6">
          <div>
            <div class="text-xs text-slate-400">最新成交量</div>
            <div class="text-base font-semibold font-mono text-slate-200 mt-0.5" id="quote-volume">-</div>
          </div>
          <div>
            <div class="text-xs text-slate-400">52 週最低</div>
            <div class="text-base font-semibold font-mono text-slate-200 mt-0.5" id="quote-low52">$0.00</div>
          </div>
          <div>
            <div class="text-xs text-slate-400">52 週最高</div>
            <div class="text-base font-semibold font-mono text-slate-200 mt-0.5" id="quote-high52">$0.00</div>
          </div>
        </div>

      </div>
    </div>

    <!-- 搜尋與篩選列 -->
    <div class="flex flex-col sm:flex-row gap-3 items-center justify-between">
      <div class="relative w-full sm:w-80">
        <input type="text" id="search-input" placeholder="搜尋推文內容、摘要或 $標的..." 
          class="w-full bg-slate-900 border border-slate-700/80 rounded-lg px-3.5 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500 transition" />
      </div>
      <div class="flex items-center gap-2 w-full sm:w-auto overflow-x-auto pb-1 sm:pb-0">
        <button onclick="setSentimentFilter('ALL')" class="filter-btn active px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-700 bg-slate-800 text-white transition" data-val="ALL">全部</button>
        <button onclick="setSentimentFilter('Bullish')" class="filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border border-transparent text-slate-400 hover:text-emerald-400 hover:bg-slate-900 transition" data-val="Bullish">看多</button>
        <button onclick="setSentimentFilter('Bearish')" class="filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border border-transparent text-slate-400 hover:text-rose-400 hover:bg-slate-900 transition" data-val="Bearish">看空</button>
        <button onclick="setSentimentFilter('Neutral')" class="filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border border-transparent text-slate-400 hover:text-blue-400 hover:bg-slate-900 transition" data-val="Neutral">中立</button>
      </div>
    </div>

    <!-- 推文卡片列表 -->
    <div class="space-y-4" id="tweets-list"></div>

  </main>

  <script>
    const allTweets = {tweets_json_str};
    const topTickers = {top_tickers_json_str};
    const stockQuotes = {stock_quotes_json_str};

    let currentSentiment = 'ALL';
    let currentTicker = topTickers.length > 0 ? topTickers[0][0] : '';
    let searchQuery = '';

    let clientTranslations = JSON.parse(localStorage.getItem('serenity_trans_cache') || '{{}}');

    function formatNumber(num) {{
      if (!num) return '-';
      if (num >= 1e9) return (num / 1e9).toFixed(2) + 'B';
      if (num >= 1e6) return (num / 1e6).toFixed(2) + 'M';
      if (num >= 1e3) return (num / 1e3).toFixed(1) + 'K';
      return num.toLocaleString();
    }}

    function highlightText(text) {{
      if (!text) return '';
      return text
        .replace(/(\\$[A-Z]{{1,5}})/g, '<button onclick="filterByTicker(\\'$1\\'.replace(\\'$\\', \\'\\'))" class="font-bold text-teal-400 bg-teal-950/60 hover:bg-teal-900/80 px-1 py-0.5 rounded border border-teal-500/30 transition inline-block">$1</button>')
        .replace(/(https?:\\/\\/[^\\s]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" class="text-cyan-400 hover:underline break-all">$1</a>');
    }}

    function renderStockQuote(ticker) {{
      const section = document.getElementById('stock-quote-section');
      if (!ticker || !stockQuotes[ticker]) {{
        section.classList.add('hidden');
        return;
      }}

      const data = stockQuotes[ticker];
      section.classList.remove('hidden');

      document.getElementById('quote-ticker-name').innerText = `$${{ticker}}`;
      document.getElementById('quote-price').innerText = `$${{data.price.toFixed(2)}}`;

      const isPositive = data.change >= 0;
      const changeEl = document.getElementById('quote-change-container');
      const changeVal = `${{isPositive ? '+' : ''}}${{data.change.toFixed(2)}}`;
      const changePctVal = `(${{isPositive ? '+' : ''}}${{data.changePct.toFixed(2)}}%)`;

      document.getElementById('quote-change').innerText = changeVal;
      document.getElementById('quote-change-pct').innerText = changePctVal;

      if (isPositive) {{
        changeEl.className = 'flex items-center gap-2 mt-0.5 text-sm font-semibold font-mono text-emerald-400';
      }} else {{
        changeEl.className = 'flex items-center gap-2 mt-0.5 text-sm font-semibold font-mono text-rose-400';
      }}

      document.getElementById('quote-volume').innerText = formatNumber(data.volume);
      document.getElementById('quote-low52').innerText = data.low52 ? `$${{data.low52.toFixed(2)}}` : '-';
      document.getElementById('quote-high52').innerText = data.high52 ? `$${{data.high52.toFixed(2)}}` : '-';
    }}

    function renderTopTickers() {{
      const bar = document.getElementById('top-tickers-bar');
      bar.innerHTML = topTickers.map(([t, count]) => {{
        const quote = stockQuotes[t];
        let miniBadge = '';
        if (quote) {{
          const isPos = quote.changePct >= 0;
          miniBadge = `<span class="text-[10px] ml-1 ${{isPos ? 'text-emerald-400' : 'text-rose-400'}}">${{isPos ? '+' : ''}}${{quote.changePct.toFixed(1)}}%</span>`;
        }}
        return `
          <button onclick="filterByTicker('${{t}}')" class="px-2.5 py-1 rounded-md text-xs font-mono font-medium border transition ${{currentTicker === t ? 'bg-teal-500 text-slate-950 border-teal-400 font-bold' : 'bg-slate-800/80 border-slate-700/60 text-slate-300 hover:border-teal-500/50'}}">
            \\$${{t}} ${{miniBadge}} <span class="text-[10px] opacity-70">(${{count}})</span>
          </button>
        `;
      }}).join('');
    }}

    function filterByTicker(ticker) {{
      currentTicker = ticker;
      document.getElementById('clear-ticker-btn').classList.toggle('hidden', !ticker);
      renderTopTickers();
      renderStockQuote(ticker);
      render();
    }}

    function setSentimentFilter(val) {{
      currentSentiment = val;
      document.querySelectorAll('.filter-btn').forEach(btn => {{
        const active = btn.dataset.val === val;
        btn.className = `filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border transition ${{
          active ? 'border-slate-700 bg-slate-800 text-white' : 'border-transparent text-slate-400 hover:bg-slate-900'
        }}`;
      }});
      render();
    }}

    async function translateByIndex(idx) {{
      const transEl = document.getElementById(`trans-text-${{idx}}`);
      const btnEl = document.getElementById(`trans-btn-${{idx}}`);
      const item = allTweets[idx];
      if (!transEl || !item) return;

      const rawText = item.text;
      if (clientTranslations[rawText]) {{
        transEl.innerHTML = highlightText(clientTranslations[rawText]);
        transEl.classList.remove('hidden');
        if (btnEl) btnEl.remove();
        return;
      }}

      try {{
        if (btnEl) btnEl.innerText = '翻譯中...';
        const url = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-TW&dt=t&q=' + encodeURIComponent(rawText);
        const res = await fetch(url);
        const json = await res.json();
        const translated = json[0].map(row => row[0]).join('');
        clientTranslations[rawText] = translated;
        localStorage.setItem('serenity_trans_cache', JSON.stringify(clientTranslations));
        transEl.innerHTML = highlightText(translated);
        transEl.classList.remove('hidden');
        if (btnEl) btnEl.remove();
      }} catch (err) {{
        console.error('翻譯失敗', err);
        if (btnEl) btnEl.innerText = '⚠️ 翻譯失敗，點擊重試';
      }}
    }}

    function render() {{
      const container = document.getElementById('tweets-list');
      const filtered = allTweets.filter(t => {{
        const matchSentiment = currentSentiment === 'ALL' || t.sentiment === currentSentiment;
        const matchTicker = !currentTicker || t.tickers.includes(currentTicker);
        const matchSearch = !searchQuery || 
          t.text.toLowerCase().includes(searchQuery) || 
          t.summary.toLowerCase().includes(searchQuery) ||
          t.tickers.some(tick => tick.toLowerCase().includes(searchQuery));
        return matchSentiment && matchTicker && matchSearch;
      }});

      if (filtered.length === 0) {{
        container.innerHTML = `
          <div class="text-center py-16 text-slate-500 bg-slate-900/30 rounded-xl border border-slate-800">
            沒有符合篩選條件的推文。
          </div>
        `;
        return;
      }}

      container.innerHTML = filtered.map(item => {{
        const globalIdx = allTweets.indexOf(item);
        const cachedClient = clientTranslations[item.text];

        let sentimentBadge = '';
        if (item.sentiment === 'Bullish') {{
          sentimentBadge = '<span class="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">看多 Bullish</span>';
        }} else if (item.sentiment === 'Bearish') {{
          sentimentBadge = '<span class="px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">看空 Bearish</span>';
        }} else {{
          sentimentBadge = '<span class="px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20">中立 Neutral</span>';
        }}

        let contentHtml = '';
        if (item.summary || item.translation_zh) {{
          contentHtml = `
            ${{item.summary ? `<div class="text-sm font-semibold text-teal-300 mb-1.5 flex items-start gap-1.5"><span class="text-teal-400 font-mono">⚡ 觀點：</span>${{item.summary}}</div>` : ''}}
            ${{item.translation_zh ? `<div class="text-slate-200 text-sm leading-relaxed whitespace-pre-wrap">${{highlightText(item.translation_zh)}}</div>` : ''}}
            <details class="mt-2 text-xs text-slate-500">
              <summary class="cursor-pointer hover:text-slate-400 select-none">查看原文</summary>
              <div class="mt-1 text-slate-400 whitespace-pre-wrap border-l-2 border-slate-700 pl-2 py-1">${{highlightText(item.text)}}</div>
            </details>
          `;
        }} else {{
          contentHtml = `
            <div id="trans-text-${{globalIdx}}" class="text-slate-200 text-sm leading-relaxed whitespace-pre-wrap font-medium mb-1 ${{cachedClient ? '' : 'hidden'}}">${{cachedClient ? highlightText(cachedClient) : ''}}</div>
            <div class="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">${{highlightText(item.text)}}</div>
            ${{cachedClient ? '' : `<button id="trans-btn-${{globalIdx}}" onclick="translateByIndex(${{globalIdx}})" class="text-xs text-teal-400 hover:text-teal-300 flex items-center gap-1 mt-2 transition">🌐 翻譯為繁體中文</button>`}}
          `;
        }}

        return `
          <article class="bg-slate-900/60 border border-slate-800 rounded-xl p-4 sm:p-5 hover:border-slate-700/80 transition space-y-3">
            <div class="flex items-center justify-between flex-wrap gap-2">
              <div class="flex items-center gap-2">
                ${{sentimentBadge}}
                <div class="flex flex-wrap gap-1">
                  ${{item.tickers.map(tk => `<button onclick="filterByTicker('${{tk}}')" class="text-xs font-mono font-bold text-teal-400 bg-slate-800 hover:bg-slate-700 px-1.5 py-0.5 rounded border border-slate-700 transition">\\$${{tk}}</button>`).join('')}}
                </div>
              </div>
              <div class="text-xs text-slate-500 font-mono">${{item.date}}</div>
            </div>

            <div class="py-1">${{contentHtml}}</div>

            <div class="flex items-center justify-between text-xs text-slate-400 border-t border-slate-800/80 pt-2.5">
              <div class="flex items-center gap-4">
                <span>❤️ ${{item.likes.toLocaleString()}}</span>
                <span>🔁 ${{item.retweets.toLocaleString()}}</span>
                <span>👁️ ${{item.views.toLocaleString()}}</span>
              </div>
              <a href="${{item.url}}" target="_blank" rel="noopener noreferrer" class="text-slate-400 hover:text-white transition flex items-center gap-1">
                開啟推文 ↗
              </a>
            </div>
          </article>
        `;
      }}).join('');
    }}

    function initStats() {{
      const total = allTweets.length;
      const bullish = allTweets.filter(t => t.sentiment === 'Bullish').length;
      const bearish = allTweets.filter(t => t.sentiment === 'Bearish').length;
      const uniqueTickers = new Set(allTweets.flatMap(t => t.tickers)).size;

      document.getElementById('stat-total').innerText = total.toLocaleString();
      document.getElementById('stat-bullish').innerText = `${{bullish}} (${{total ? Math.round(bullish/total*100) : 0}}%)`;
      document.getElementById('stat-bearish').innerText = `${{bearish}} (${{total ? Math.round(bearish/total*100) : 0}}%)`;
      document.getElementById('stat-tickers').innerText = uniqueTickers.toLocaleString();
      document.getElementById('last-update-time').innerText = `建置時間：${{new Date().toLocaleString('zh-TW', {{ hour12: false }})}}`;
    }}

    document.getElementById('search-input').addEventListener('input', (e) => {{
      searchQuery = e.target.value.trim().toLowerCase();
      render();
    }});

    // 初始化載入
    initStats();
    renderTopTickers();
    renderStockQuote(currentTicker);
    render();
  </script>
</body>
</html>
"""
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ 儀表板成功產出至 {OUTPUT_HTML}")

if __name__ == "__main__":
    tweets_raw = load_tweets(TWEETS_FILE)
    sentiment_cache = load_cache(CACHE_FILE)
    cleaned_tweets, counts = clean_tweet_data(tweets_raw, sentiment_cache)
    
    # 取出現次數最高的前 30 個標的抓取即時行情
    top_tickers_list = [t[0] for t in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:30]]
    stock_quotes = fetch_stock_quotes(top_tickers_list)
    
    generate_html(cleaned_tweets, counts, stock_quotes)
