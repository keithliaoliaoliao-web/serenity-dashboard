import json
import re
import os
from datetime import datetime

TWEETS_FILE = "data/tweets.json"
CACHE_FILE = "data/sentiment_cache.json"
OUTPUT_HTML = "docs/index.html"

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def extract_tickers(text):
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Z]{1,5})\b", text.upper())
    blacklist = {"USD", "CAD", "EUR", "ATH", "CEO", "AI", "FOMC", "FED", "CPI", "GDP"}
    return [t for t in set(matches) if t not in blacklist]

def rule_based_sentiment(text):
    t = text.lower()
    bull_words = ["long", "call", "calls", "breakout", "accumulate", "higher", "ath", "bounce", "bottom", "support", "target", "rip", "buying", "bullish", "moon"]
    bear_words = ["short", "put", "puts", "breakdown", "dump", "lower", "crash", "resistance", "drop", "selling", "bearish", "flush", "top"]
    bull_score = sum(1 for w in bull_words if re.search(r'\b' + re.escape(w) + r'\b', t))
    bear_score = sum(1 for w in bear_words if re.search(r'\b' + re.escape(w) + r'\b', t))
    if bull_score > bear_score:
        return "Bullish"
    elif bear_score > bull_score:
        return "Bearish"
    return "Neutral"

def clean_tweet_data(raw_tweets, sentiment_cache):
    cleaned = []
    ticker_counts = {}
    
    for item in raw_tweets:
        text = item.get("text") or item.get("full_text") or ""
        if not text:
            continue
        
        tweet_id = str(item.get("id") or item.get("id_str") or item.get("tweet_id") or "")
        created_at = item.get("created_at") or ""
        
        time_str = created_at
        try:
            if "T" in created_at:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            elif len(created_at.split()) >= 6:
                dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                time_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            time_str = created_at[:16]

        tickers = extract_tickers(text)
        
        # 優先採用 Gemini AI 情緒與摘要
        ai_data = sentiment_cache.get(tweet_id)
        if ai_data:
            sentiment = ai_data.get("sentiment", "Neutral")
            summary = ai_data.get("summary", "")
            is_ai = True
        else:
            sentiment = rule_based_sentiment(text)
            summary = ""
            is_ai = False
        
        for ticker in tickers:
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
        
        likes = item.get("favorite_count", item.get("likes", 0)) or 0
        retweets = item.get("retweet_count", item.get("retweets", 0)) or 0
        views = item.get("views", item.get("view_count", 0)) or 0

        cleaned.append({
            "id": tweet_id,
            "text": text,
            "time": time_str,
            "tickers": tickers,
            "sentiment": sentiment,
            "summary": summary,
            "is_ai": is_ai,
            "likes": int(likes),
            "retweets": int(retweets),
            "views": int(views) if str(views).isdigit() else 0
        })
    
    cleaned.sort(key=lambda x: x["time"], reverse=True)
    return cleaned, ticker_counts

def generate_html(tweets, ticker_counts):
    total_tweets = len(tweets)
    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:25]
    bull_count = sum(1 for t in tweets if t["sentiment"] == "Bullish")
    bear_count = sum(1 for t in tweets if t["sentiment"] == "Bearish")
    
    tweets_json_str = json.dumps(tweets, ensure_ascii=False)
    top_tickers_json = json.dumps(top_tickers, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-Hant" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Serenity (@aleabitoreddit) Stock Tracker</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          colors: {{
            brandDark: '#080b11',
            cardDark: '#0f172a',
            cardBorder: '#1e293b',
            accentCyan: '#06b6d4',
            bullGreen: '#10b981',
            bearRed: '#f43f5e',
          }}
        }}
      }}
    }}
  </script>
  <style>
    body {{ background-color: #080b11; color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    .ticker-pill:hover {{ transform: translateY(-1px); }}
  </style>
</head>
<body class="min-h-screen p-3 md:p-8">
  <div class="max-w-6xl mx-auto space-y-6">
    
    <header class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-6 border-b border-cardBorder">
      <div>
        <div class="flex items-center gap-3">
          <h1 class="text-2xl md:text-3xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>🔭 Serenity Tracker</span>
          </h1>
          <span class="bg-cyan-500/10 text-cyan-400 text-xs px-2.5 py-1 rounded-full border border-cyan-500/20 font-medium">
            @aleabitoreddit
          </span>
        </div>
        <p class="text-slate-400 text-sm mt-1">即時個股觀點、情緒分析與歷史推文儀表板</p>
      </div>
      <div class="text-xs text-slate-400 bg-cardDark px-4 py-2 rounded-lg border border-cardBorder">
        最後更新：<span id="update-time" class="text-slate-200 font-medium">{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
      </div>
    </header>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">總追蹤推文</div>
        <div class="text-2xl font-bold text-white mt-1">{total_tweets:,}</div>
      </div>
      <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">提及標的數</div>
        <div class="text-2xl font-bold text-cyan-400 mt-1">{len(ticker_counts)}</div>
      </div>
      <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">看多觀點 (Bullish)</div>
        <div class="text-2xl font-bold text-emerald-400 mt-1">{bull_count:,}</div>
      </div>
      <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">看空/警戒 (Bearish)</div>
        <div class="text-2xl font-bold text-rose-400 mt-1">{bear_count:,}</div>
      </div>
    </div>

    <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
      <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">熱門提及標的 (點擊快速篩選)</div>
      <div id="top-tickers-container" class="flex flex-wrap gap-2"></div>
    </div>

    <div class="flex flex-col md:flex-row gap-3 items-stretch md:items-center justify-between">
      <div class="relative flex-1">
        <input type="text" id="search-input" placeholder="搜尋標的代號 (例如 NVDA) 或推文關鍵字..." 
          class="w-full bg-cardDark border border-cardBorder rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition">
      </div>
      <div class="flex items-center gap-2">
        <select id="sentiment-filter" class="bg-cardDark border border-cardBorder text-slate-300 text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-cyan-500">
          <option value="ALL">全部情緒</option>
          <option value="Bullish">🟢 看多 (Bullish)</option>
          <option value="Bearish">🔴 看空 (Bearish)</option>
          <option value="Neutral">⚪ 中立 (Neutral)</option>
        </select>
        <select id="sort-order" class="bg-cardDark border border-cardBorder text-slate-300 text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-cyan-500">
          <option value="newest">最新發布</option>
          <option value="likes">最多按讚</option>
          <option value="retweets">最多轉推</option>
        </select>
      </div>
    </div>

    <div class="text-xs text-slate-400 px-1">
      符合條件推文：<span id="filtered-count" class="text-cyan-400 font-semibold">0</span> 則
    </div>

    <div id="tweets-feed" class="space-y-4"></div>

    <div class="text-center pt-4 pb-12">
      <button id="load-more-btn" class="bg-cardDark hover:bg-slate-800 text-slate-300 border border-cardBorder px-6 py-2.5 rounded-lg text-sm font-medium transition duration-150">
        載入更多推文
      </button>
    </div>

  </div>

  <script>
    const ALL_TWEETS = {tweets_json_str};
    const TOP_TICKERS = {top_tickers_json};
    
    let filteredTweets = [...ALL_TWEETS];
    let currentPage = 1;
    const PAGE_SIZE = 25;
    let selectedTicker = null;

    const topContainer = document.getElementById('top-tickers-container');
    TOP_TICKERS.forEach(([ticker, count]) => {{
      const btn = document.createElement('button');
      btn.className = "ticker-pill px-3 py-1 bg-slate-800/80 hover:bg-cyan-950/60 border border-slate-700/80 hover:border-cyan-500/50 rounded-lg text-xs font-mono text-cyan-300 transition";
      btn.innerHTML = `<span class="font-bold">$${{ticker}}</span> <span class="text-slate-400 text-[10px]">(${{count}})</span>`;
      btn.onclick = () => {{
        if (selectedTicker === ticker) {{
          selectedTicker = null;
          document.getElementById('search-input').value = '';
        }} else {{
          selectedTicker = ticker;
          document.getElementById('search-input').value = `$${{ticker}}`;
        }}
        applyFilters();
      }};
      topContainer.appendChild(btn);
    }});

    function highlightText(text) {{
      return text
        .replace(/(\$[A-Z]{{1,5}}\b)/g, '<span class="text-cyan-400 font-semibold">$1</span>')
        .replace(/(https?:\\/\\/[^\\s]+)/g, '<a href="$1" target="_blank" class="text-cyan-500 hover:underline break-all">$1</a>');
    }}

    function applyFilters() {{
      const query = document.getElementById('search-input').value.trim().toLowerCase();
      const sentiment = document.getElementById('sentiment-filter').value;
      const sort = document.getElementById('sort-order').value;

      filteredTweets = ALL_TWEETS.filter(item => {{
        const matchesQuery = !query || item.text.toLowerCase().includes(query) || item.tickers.some(t => ('$' + t.toLowerCase()).includes(query) || t.toLowerCase().includes(query));
        const matchesSentiment = sentiment === 'ALL' || item.sentiment === sentiment;
        return matchesQuery && matchesSentiment;
      }});

      if (sort === 'likes') {{
        filteredTweets.sort((a, b) => b.likes - a.likes);
      }} else if (sort === 'retweets') {{
        filteredTweets.sort((a, b) => b.retweets - a.retweets);
      }} else {{
        filteredTweets.sort((a, b) => (b.time > a.time ? 1 : -1));
      }}

      document.getElementById('filtered-count').innerText = filteredTweets.length.toLocaleString();
      currentPage = 1;
      renderFeed();
    }}

    function renderFeed() {{
      const feed = document.getElementById('tweets-feed');
      if (currentPage === 1) {{
        feed.innerHTML = '';
      }}

      const slice = filteredTweets.slice(0, currentPage * PAGE_SIZE);
      const toAppend = filteredTweets.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

      if (slice.length === 0) {{
        feed.innerHTML = '<div class="text-center py-16 text-slate-500 text-sm">找不到符合條件的推文</div>';
        document.getElementById('load-more-btn').style.display = 'none';
        return;
      }}

      toAppend.forEach(item => {{
        const card = document.createElement('div');
        card.className = "bg-cardDark border border-cardBorder p-5 rounded-xl transition hover:border-slate-600 space-y-3";
        
        let badgeColor = "bg-slate-800 text-slate-400 border-slate-700";
        if (item.sentiment === 'Bullish') badgeColor = "bg-emerald-950/60 text-emerald-400 border-emerald-800/60";
        if (item.sentiment === 'Bearish') badgeColor = "bg-rose-950/60 text-rose-400 border-rose-800/60";

        const aiTag = item.is_ai ? '<span class="text-[10px] bg-purple-950/80 text-purple-300 border border-purple-800/60 px-1.5 py-0.5 rounded font-mono">✨ Gemini AI</span>' : '';
        const summaryHtml = item.summary ? `<div class="text-xs text-slate-400 bg-slate-900/80 border border-slate-800 p-2.5 rounded-lg"><span class="text-purple-300 font-semibold">觀點摘要：</span>${{item.summary}}</div>` : '';

        const tickerTags = item.tickers.map(t => 
          `<span class="bg-cyan-950/50 text-cyan-300 text-xs px-2 py-0.5 rounded border border-cyan-800/50 font-mono font-medium">$${{t}}</span>`
        ).join(" ");

        card.innerHTML = `
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-xs px-2.5 py-0.5 rounded-full border font-semibold ${{badgeColor}}">
                ${{item.sentiment}}
              </span>
              ${{aiTag}}
              ${{tickerTags}}
            </div>
            <a href="https://x.com/aleabitoreddit/status/${{item.id}}" target="_blank" class="text-slate-500 hover:text-slate-300 text-xs flex items-center gap-1 transition">
              <span>${{item.time}}</span>
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
            </a>
          </div>
          ${{summaryHtml}}
          <div class="text-slate-200 text-sm leading-relaxed whitespace-pre-wrap">${{highlightText(item.text)}}</div>
          <div class="flex items-center gap-5 pt-2 text-xs text-slate-500 border-t border-cardBorder/60">
            <span class="flex items-center gap-1">❤️ ${{item.likes.toLocaleString()}}</span>
            <span class="flex items-center gap-1">🔁 ${{item.retweets.toLocaleString()}}</span>
            ${{item.views ? `<span class="flex items-center gap-1">👁️ ${{item.views.toLocaleString()}}</span>` : ''}}
          </div>
        `;
        feed.appendChild(card);
      }});

      const loadMoreBtn = document.getElementById('load-more-btn');
      loadMoreBtn.style.display = slice.length >= filteredTweets.length ? 'none' : 'inline-block';
    }}

    document.getElementById('search-input').addEventListener('input', applyFilters);
    document.getElementById('sentiment-filter').addEventListener('change', applyFilters);
    document.getElementById('sort-order').addEventListener('change', applyFilters);
    document.getElementById('load-more-btn').addEventListener('click', () => {{
      currentPage++;
      renderFeed();
    }});

    applyFilters();
  </script>
</body>
</html>
"""
    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ 儀表板成功產出至 {OUTPUT_HTML}")

if __name__ == "__main__":
    tweets_raw = load_json(TWEETS_FILE, [])
    sentiment_cache = load_json(CACHE_FILE, {})
    cleaned_tweets, counts = clean_tweet_data(tweets_raw, sentiment_cache)
    generate_html(cleaned_tweets, counts)
