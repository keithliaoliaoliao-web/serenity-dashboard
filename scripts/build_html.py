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
        month_key = ""
        try:
            if "T" in created_at:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                time_str = dt.strftime("%Y-%m-%d %H:%M")
                month_key = dt.strftime("%Y-%m")
            elif len(created_at.split()) >= 6:
                dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                time_str = dt.strftime("%Y-%m-%d %H:%M")
                month_key = dt.strftime("%Y-%m")
        except Exception:
            time_str = created_at[:16]
            month_key = created_at[:7] if len(created_at) >= 7 else "Unknown"

        tickers = extract_tickers(text)
        
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
            "month": month_key,
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
    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:30]
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
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
    .active-pill {{ border-color: #06b6d4 !important; background-color: rgba(6, 182, 212, 0.18) !important; }}
  </style>
</head>
<body class="min-h-screen p-3 md:p-8">
  <div class="max-w-6xl mx-auto space-y-6">
    
    <!-- Top Header -->
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
        <p class="text-slate-400 text-sm mt-1">即時個股觀點、多空時間線與歷史推文儀表板</p>
      </div>
      <div class="text-xs text-slate-400 bg-cardDark px-4 py-2 rounded-lg border border-cardBorder">
        最後更新：<span id="update-time" class="text-slate-200 font-medium">{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
      </div>
    </header>

    <!-- Global Metrics Grid -->
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

    <!-- Top Mentioned Tickers -->
    <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
      <div class="flex items-center justify-between mb-3">
        <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">熱門提及標的 (點擊展開個股深度分析)</div>
        <button id="clear-filter-btn" class="text-xs text-slate-500 hover:text-cyan-400 hidden">清除篩選</button>
      </div>
      <div id="top-tickers-container" class="flex flex-wrap gap-2"></div>
    </div>

    <!-- Ticker Deep Dive Panel (Hidden by default, shown when a ticker is selected) -->
    <div id="ticker-analytics-panel" class="hidden bg-slate-900/90 border border-cyan-500/30 rounded-2xl p-5 md:p-6 space-y-6">
      <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-3 pb-4 border-b border-slate-800">
        <div>
          <div class="flex items-center gap-3">
            <h2 id="analytics-ticker-title" class="text-2xl font-mono font-bold text-cyan-400">$TICKER</h2>
            <span id="analytics-ticker-count" class="bg-slate-800 text-slate-300 text-xs px-2.5 py-1 rounded-full border border-slate-700 font-mono">0 則推文</span>
          </div>
          <p class="text-xs text-slate-400 mt-1">歷史討論多空分佈與提及趨勢分析</p>
        </div>
        <div class="flex gap-4 text-xs font-medium">
          <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>看多: <span id="ticker-bull-pct" class="text-white font-bold">0%</span></div>
          <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-rose-500"></span>看空: <span id="ticker-bear-pct" class="text-white font-bold">0%</span></div>
          <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-slate-500"></span>中立: <span id="ticker-neutral-pct" class="text-white font-bold">0%</span></div>
        </div>
      </div>

      <!-- Ratio Bar -->
      <div class="space-y-1.5">
        <div class="text-[11px] text-slate-400 font-medium">觀點情緒分佈比例</div>
        <div class="h-3 w-full bg-slate-800 rounded-full overflow-hidden flex">
          <div id="bar-bull" class="bg-emerald-500 h-full transition-all duration-500" style="width: 0%"></div>
          <div id="bar-bear" class="bg-rose-500 h-full transition-all duration-500" style="width: 0%"></div>
          <div id="bar-neutral" class="bg-slate-600 h-full transition-all duration-500" style="width: 0%"></div>
        </div>
      </div>

      <!-- Timeline Chart -->
      <div>
        <div class="text-[11px] text-slate-400 font-medium mb-2">歷史月份提及趨勢圖</div>
        <div class="h-48 w-full">
          <canvas id="tickerTimelineChart"></canvas>
        </div>
      </div>
    </div>

    <!-- Search and Controls -->
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

    <!-- Results Counter -->
    <div class="text-xs text-slate-400 px-1">
      符合條件推文：<span id="filtered-count" class="text-cyan-400 font-semibold">0</span> 則
    </div>

    <!-- Tweet Feed List -->
    <div id="tweets-feed" class="space-y-4"></div>

    <!-- Load More Button -->
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
    let chartInstance = null;

    const topContainer = document.getElementById('top-tickers-container');
    const clearBtn = document.getElementById('clear-filter-btn');

    TOP_TICKERS.forEach(([ticker, count]) => {{
      const btn = document.createElement('button');
      btn.id = `ticker-btn-${{ticker}}`;
      btn.className = "ticker-pill px-3 py-1 bg-slate-800/80 hover:bg-cyan-950/60 border border-slate-700/80 hover:border-cyan-500/50 rounded-lg text-xs font-mono text-cyan-300 transition";
      btn.innerHTML = `<span class="font-bold">$${{ticker}}</span> <span class="text-slate-400 text-[10px]">(${{count}})</span>`;
      btn.onclick = () => {{
        if (selectedTicker === ticker) {{
          clearActiveTicker();
        }} else {{
          selectTicker(ticker);
        }}
      }};
      topContainer.appendChild(btn);
    }});

    clearBtn.onclick = clearActiveTicker;

    function selectTicker(ticker) {{
      selectedTicker = ticker;
      document.querySelectorAll('.ticker-pill').forEach(el => el.classList.remove('active-pill'));
      const activeEl = document.getElementById(`ticker-btn-${{ticker}}`);
      if (activeEl) activeEl.classList.add('active-pill');
      clearBtn.classList.remove('hidden');
      document.getElementById('search-input').value = `$${{ticker}}`;
      
      renderTickerAnalytics(ticker);
      applyFilters();
    }}

    function clearActiveTicker() {{
      selectedTicker = null;
      document.querySelectorAll('.ticker-pill').forEach(el => el.classList.remove('active-pill'));
      clearBtn.classList.add('hidden');
      document.getElementById('ticker-analytics-panel').classList.add('hidden');
      document.getElementById('search-input').value = '';
      applyFilters();
    }}

    function renderTickerAnalytics(ticker) {{
      const tickerTweets = ALL_TWEETS.filter(t => t.tickers.includes(ticker));
      const total = tickerTweets.length;
      if (total === 0) return;

      document.getElementById('ticker-analytics-panel').classList.remove('hidden');
      document.getElementById('analytics-ticker-title').innerText = `$${{ticker}}`;
      document.getElementById('analytics-ticker-count').innerText = `${{total}} 則推文`;

      const bull = tickerTweets.filter(t => t.sentiment === 'Bullish').length;
      const bear = tickerTweets.filter(t => t.sentiment === 'Bearish').length;
      const neutral = total - bull - bear;

      const bullPct = Math.round((bull / total) * 100);
      const bearPct = Math.round((bear / total) * 100);
      const neutralPct = 100 - bullPct - bearPct;

      document.getElementById('ticker-bull-pct').innerText = `${{bullPct}}% (${{bull}})`;
      document.getElementById('ticker-bear-pct').innerText = `${{bearPct}}% (${{bear}})`;
      document.getElementById('ticker-neutral-pct').innerText = `${{neutralPct}}% (${{neutral}})`;

      document.getElementById('bar-bull').style.width = `${{bullPct}}%`;
      document.getElementById('bar-bear').style.width = `${{bearPct}}%`;
      document.getElementById('bar-neutral').style.width = `${{neutralPct}}%`;

      // 彙整月度統計
      const monthlyMap = {{}};
      tickerTweets.forEach(t => {{
        if (!t.month || t.month.length < 7) return;
        if (!monthlyMap[t.month]) {{
          monthlyMap[t.month] = {{ bull: 0, bear: 0, neutral: 0 }};
        }}
        if (t.sentiment === 'Bullish') monthlyMap[t.month].bull++;
        else if (t.sentiment === 'Bearish') monthlyMap[t.month].bear++;
        else monthlyMap[t.month].neutral++;
      }});

      const sortedMonths = Object.keys(monthlyMap).sort().slice(-12);
      const labels = sortedMonths;
      const bullData = sortedMonths.map(m => monthlyMap[m].bull);
      const bearData = sortedMonths.map(m => monthlyMap[m].bear);
      const neutralData = sortedMonths.map(m => monthlyMap[m].neutral);

      const ctx = document.getElementById('tickerTimelineChart').getContext('2d');
      if (chartInstance) chartInstance.destroy();

      chartInstance = new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: labels,
          datasets: [
            {{ label: '看多 (Bullish)', data: bullData, backgroundColor: '#10b981', stack: 'Stack 0' }},
            {{ label: '看空 (Bearish)', data: bearData, backgroundColor: '#f43f5e', stack: 'Stack 0' }},
            {{ label: '中立 (Neutral)', data: neutralData, backgroundColor: '#475569', stack: 'Stack 0' }}
          ]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }}
          }},
          scales: {{
            x: {{ stacked: true, ticks: {{ color: '#64748b' }}, grid: {{ display: false }} }},
            y: {{ stacked: true, ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e293b' }} }}
          }}
        }}
      }});
    }}

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
          `<button onclick="selectTicker('${{t}}')" class="bg-cyan-950/50 hover:bg-cyan-900/60 text-cyan-300 text-xs px-2 py-0.5 rounded border border-cyan-800/50 font-mono font-medium transition cursor-pointer">$${{t}}</button>`
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

    document.getElementById('search-input').addEventListener('input', () => {{
      const val = document.getElementById('search-input').value.trim().toUpperCase();
      if (val.startsWith('$')) {{
        const sym = val.replace('$', '');
        if (TOP_TICKERS.some(t => t[0] === sym)) {{
          renderTickerAnalytics(sym);
        }}
      }}
      applyFilters();
    }});

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
