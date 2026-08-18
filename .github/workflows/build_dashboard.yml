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
                data = json.load(f)
                if isinstance(data, dict):
                    data = data.get("tweets", data.get("data", list(data.values())))
                return data
        except Exception as e:
            print(f"讀取 {filepath} 失敗: {e}")
            return default
    return default

def extract_tickers(text):
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Z]{1,5})\b", text.upper())
    blacklist = {"USD", "CAD", "EUR", "ATH", "CEO", "AI", "FOMC", "FED", "CPI", "GDP", "DD", "EOD", "YOLO"}
    return [t for t in set(matches) if t not in blacklist]

def rule_based_sentiment(text):
    t = text.lower()
    bull_words = ["long", "call", "calls", "breakout", "accumulate", "higher", "ath", "bounce", "bottom", "support", "target", "rip", "buying", "bullish", "moon", "bought", "load"]
    bear_words = ["short", "put", "puts", "breakdown", "dump", "lower", "crash", "resistance", "drop", "selling", "bearish", "flush", "top", "sold", "fade"]
    bull_score = sum(1 for w in bull_words if re.search(r'\b' + re.escape(w) + r'\b', t))
    bear_score = sum(1 for w in bear_words if re.search(r'\b' + re.escape(w) + r'\b', t))
    if bull_score > bear_score:
        return "Bullish"
    elif bear_score > bull_score:
        return "Bearish"
    return "Neutral"

def extract_tweet_id(item):
    for k in ["id", "id_str", "tweet_id", "tweetId", "rest_id", "conversation_id"]:
        if k in item and item[k]:
            return str(item[k])
    url = item.get("url") or item.get("permanentUrl") or item.get("link") or ""
    if url:
        m = re.search(r"status/(\d+)", str(url))
        if m:
            return m.group(1)
    return ""

def extract_tweet_text(item):
    for k in ["text", "rawContent", "full_text", "content", "tweet", "body", "message"]:
        if k in item and item[k]:
            return str(item[k])
    legacy = item.get("legacy") or {}
    if isinstance(legacy, dict) and "full_text" in legacy:
        return str(legacy["full_text"])
    return ""

def parse_date(item):
    raw_date = None
    for k in ["date", "created_at", "createdAt", "timestamp", "datetime", "date_time", "time", "published_at", "pubDate"]:
        if k in item and item[k]:
            raw_date = item[k]
            break
    if not raw_date:
        legacy = item.get("legacy") or {}
        if isinstance(legacy, dict):
            raw_date = legacy.get("created_at")

    if not raw_date:
        return "未知時間", "未知月份"

    if isinstance(raw_date, (int, float)):
        try:
            dt = datetime.fromtimestamp(raw_date / 1000.0 if raw_date > 1e11 else raw_date)
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
        month_str = f"{int(y):04d}-{int(mth):02d}"
        time_str = f"{int(y):04d}-{int(mth):02d}-{int(d):02d}"
        tm = re.search(r"(\d{1,2}):(\d{2})", s)
        if tm:
            time_str += f" {int(tm.group(1)):02d}:{tm.group(2)}"
        return time_str, month_str

    return s[:16], s[:7]

def extract_metrics(item):
    likes, retweets, views = 0, 0, 0
    containers = [item, item.get("public_metrics"), item.get("metrics"), item.get("stats"), item.get("legacy")]

    def get_num(d, keys):
        if not isinstance(d, dict): return None
        for k in keys:
            if k in d and d[k] is not None and str(d[k]).isdigit():
                return int(d[k])
        return None

    for c in containers:
        if not isinstance(c, dict): continue
        if likes == 0:
            val = get_num(c, ["likeCount", "likes", "like_count", "favorite_count", "favorites", "favoriteCount", "favs"])
            if val is not None: likes = val
        if retweets == 0:
            val = get_num(c, ["retweetCount", "retweets", "retweet_count", "reposts", "retweets_count", "rts"])
            if val is not None: retweets = val
        if views == 0:
            val = get_num(c, ["viewCount", "views", "view_count", "views_count", "impressionCount", "impression_count"])
            if val is not None: views = val

    return likes, retweets, views

def clean_tweet_data(raw_tweets, sentiment_cache):
    cleaned = []
    ticker_counts = {}
    
    for item in raw_tweets:
        text = extract_tweet_text(item)
        if not text:
            continue
        
        tweet_id = extract_tweet_id(item)
        time_str, month_key = parse_date(item)
        tickers = extract_tickers(text)
        likes, retweets, views = extract_metrics(item)
        
        ai_data = sentiment_cache.get(tweet_id) if tweet_id else None
        if ai_data:
            sentiment = ai_data.get("sentiment", "Neutral")
            summary = ai_data.get("summary", "")
            translation_zh = ai_data.get("translation_zh", "")
            is_ai = True
        else:
            sentiment = rule_based_sentiment(text)
            summary = ""
            translation_zh = ""
            is_ai = False
        
        for ticker in tickers:
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

        cleaned.append({
            "id": tweet_id,
            "text": text,
            "time": time_str,
            "month": month_key,
            "tickers": tickers,
            "sentiment": sentiment,
            "summary": summary,
            "translation_zh": translation_zh,
            "is_ai": is_ai,
            "likes": likes,
            "retweets": retweets,
            "views": views
        })
    
    cleaned.sort(key=lambda x: x["time"], reverse=True)
    return cleaned, ticker_counts

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Serenity (@aleabitoreddit) Stock Tracker</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brandDark: '#080b11',
            cardDark: '#0f172a',
            cardBorder: '#1e293b',
            accentCyan: '#06b6d4',
            bullGreen: '#10b981',
            bearRed: '#f43f5e',
          }
        }
      }
    }
  </script>
  <style>
    body { background-color: #080b11; color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .ticker-pill:hover { transform: translateY(-1px); }
    .active-pill { border-color: #06b6d4 !important; background-color: rgba(6, 182, 212, 0.25) !important; color: #38bdf8 !important; }
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
        <p class="text-slate-400 text-sm mt-1">即時美股推文追蹤、Gemini 繁中翻譯、情緒分析與多空歷史趨勢</p>
      </div>
      <div class="text-xs text-slate-400 bg-cardDark px-4 py-2 rounded-lg border border-cardBorder">
        最後更新：<span id="update-time" class="text-slate-200 font-medium">__UPDATE_TIME__</span>
      </div>
    </header>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">總追蹤推文</div>
        <div class="text-2xl font-bold text-white mt-1">__TOTAL_TWEETS__</div>
      </div>
      <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">提及標的數</div>
        <div class="text-2xl font-bold text-cyan-400 mt-1">__TICKER_COUNT__</div>
      </div>
      <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">看多觀點 (Bullish)</div>
        <div class="text-2xl font-bold text-emerald-400 mt-1">__BULL_COUNT__</div>
      </div>
      <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">看空/警戒 (Bearish)</div>
        <div class="text-2xl font-bold text-rose-400 mt-1">__BEAR_COUNT__</div>
      </div>
    </div>

    <div class="bg-cardDark border border-cardBorder p-4 rounded-xl">
      <div class="flex items-center justify-between mb-3">
        <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">熱門提及標的 (點擊展開個股趨勢圖)</div>
        <button id="clear-filter-btn" class="text-xs text-slate-500 hover:text-cyan-400 hidden">清除標的篩選</button>
      </div>
      <div id="top-tickers-container" class="flex flex-wrap gap-2"></div>
    </div>

    <div id="ticker-analytics-panel" class="hidden bg-slate-900/95 border border-cyan-500/40 rounded-2xl p-5 md:p-6 space-y-5">
      <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-3 pb-4 border-b border-slate-800">
        <div>
          <div class="flex items-center gap-3">
            <h2 id="analytics-ticker-title" class="text-2xl font-mono font-bold text-cyan-400">$TICKER</h2>
            <span id="analytics-ticker-count" class="bg-slate-800 text-slate-300 text-xs px-2.5 py-1 rounded-full border border-slate-700 font-mono">0 則推文</span>
          </div>
          <p class="text-xs text-slate-400 mt-1">歷史討論多空分佈與月度提及趨勢</p>
        </div>
        <div class="flex gap-4 text-xs font-medium">
          <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>看多: <span id="ticker-bull-pct" class="text-white font-bold">0%</span></div>
          <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-rose-500"></span>看空: <span id="ticker-bear-pct" class="text-white font-bold">0%</span></div>
          <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-slate-500"></span>中立: <span id="ticker-neutral-pct" class="text-white font-bold">0%</span></div>
        </div>
      </div>

      <div class="space-y-1.5">
        <div class="text-[11px] text-slate-400 font-medium">情緒多空比例</div>
        <div class="h-3 w-full bg-slate-800 rounded-full overflow-hidden flex">
          <div id="bar-bull" class="bg-emerald-500 h-full transition-all duration-500" style="width: 0%"></div>
          <div id="bar-bear" class="bg-rose-500 h-full transition-all duration-500" style="width: 0%"></div>
          <div id="bar-neutral" class="bg-slate-600 h-full transition-all duration-500" style="width: 0%"></div>
        </div>
      </div>

      <div>
        <div class="text-[11px] text-slate-400 font-medium mb-2">歷史月份提及趨勢圖</div>
        <div class="h-56 w-full relative">
          <canvas id="tickerTimelineChart"></canvas>
        </div>
      </div>
    </div>

    <div class="flex flex-col md:flex-row gap-3 items-stretch md:items-center justify-between">
      <div class="relative flex-1">
        <input type="text" id="search-input" placeholder="搜尋標的代號 (例如 $NVDA) 或關鍵字..." 
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
    const ALL_TWEETS = __TWEETS_JSON__;
    const TOP_TICKERS = __TOP_TICKERS_JSON__;
    
    let filteredTweets = [...ALL_TWEETS];
    let currentPage = 1;
    const PAGE_SIZE = 25;
    let selectedTicker = null;
    let chartInstance = null;
    const clientTranslations = JSON.parse(localStorage.getItem('serenity_trans_cache') || '{}');

    const topContainer = document.getElementById('top-tickers-container');
    const clearBtn = document.getElementById('clear-filter-btn');

    TOP_TICKERS.forEach(([ticker, count]) => {
      const btn = document.createElement('button');
      btn.id = `ticker-btn-${ticker}`;
      btn.className = "ticker-pill px-3 py-1 bg-slate-800/80 hover:bg-cyan-950/60 border border-slate-700/80 hover:border-cyan-500/50 rounded-lg text-xs font-mono text-cyan-300 transition";
      btn.innerHTML = `<span class="font-bold">$${ticker}</span> <span class="text-slate-400 text-[10px]">(${count})</span>`;
      btn.onclick = () => {
        if (selectedTicker === ticker) {
          clearActiveTicker();
        } else {
          selectTicker(ticker);
        }
      };
      topContainer.appendChild(btn);
    });

    clearBtn.onclick = clearActiveTicker;

    function selectTicker(ticker) {
      selectedTicker = ticker;
      document.querySelectorAll('.ticker-pill').forEach(el => el.classList.remove('active-pill'));
      const activeEl = document.getElementById(`ticker-btn-${ticker}`);
      if (activeEl) activeEl.classList.add('active-pill');
      clearBtn.classList.remove('hidden');
      document.getElementById('search-input').value = `$${ticker}`;
      
      renderTickerAnalytics(ticker);
      applyFilters();
    }

    function clearActiveTicker() {
      selectedTicker = null;
      document.querySelectorAll('.ticker-pill').forEach(el => el.classList.remove('active-pill'));
      clearBtn.classList.add('hidden');
      document.getElementById('ticker-analytics-panel').classList.add('hidden');
      document.getElementById('search-input').value = '';
      applyFilters();
    }

    function renderTickerAnalytics(ticker) {
      const tickerTweets = ALL_TWEETS.filter(t => t.tickers.includes(ticker));
      const total = tickerTweets.length;
      if (total === 0) return;

      document.getElementById('ticker-analytics-panel').classList.remove('hidden');
      document.getElementById('analytics-ticker-title').innerText = `$${ticker}`;
      document.getElementById('analytics-ticker-count').innerText = `${total} 則推文`;

      const bull = tickerTweets.filter(t => t.sentiment === 'Bullish').length;
      const bear = tickerTweets.filter(t => t.sentiment === 'Bearish').length;
      const neutral = total - bull - bear;

      const bullPct = total > 0 ? Math.round((bull / total) * 100) : 0;
      const bearPct = total > 0 ? Math.round((bear / total) * 100) : 0;
      const neutralPct = total > 0 ? (100 - bullPct - bearPct) : 0;

      document.getElementById('ticker-bull-pct').innerText = `${bullPct}% (${bull})`;
      document.getElementById('ticker-bear-pct').innerText = `${bearPct}% (${bear})`;
      document.getElementById('ticker-neutral-pct').innerText = `${neutralPct}% (${neutral})`;

      document.getElementById('bar-bull').style.width = `${bullPct}%`;
      document.getElementById('bar-bear').style.width = `${bearPct}%`;
      document.getElementById('bar-neutral').style.width = `${neutralPct}%`;

      const monthlyMap = {};
      tickerTweets.forEach(t => {
        const m = t.month || "";
        if (!m || m.includes("未知") || !m.includes("-")) return;
        if (!monthlyMap[m]) {
          monthlyMap[m] = { bull: 0, bear: 0, neutral: 0 };
        }
        if (t.sentiment === 'Bullish') monthlyMap[m].bull++;
        else if (t.sentiment === 'Bearish') monthlyMap[m].bear++;
        else monthlyMap[m].neutral++;
      });

      const sortedMonths = Object.keys(monthlyMap).sort();
      const recentMonths = sortedMonths.slice(-16);

      const labels = recentMonths;
      const bullData = recentMonths.map(m => monthlyMap[m].bull);
      const bearData = recentMonths.map(m => monthlyMap[m].bear);
      const neutralData = recentMonths.map(m => monthlyMap[m].neutral);

      const ctx = document.getElementById('tickerTimelineChart').getContext('2d');
      if (chartInstance) chartInstance.destroy();

      chartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [
            { label: '看多 (Bullish)', data: bullData, backgroundColor: '#10b981', stack: 'Stack 0' },
            { label: '看空 (Bearish)', data: bearData, backgroundColor: '#f43f5e', stack: 'Stack 0' },
            { label: '中立 (Neutral)', data: neutralData, backgroundColor: '#475569', stack: 'Stack 0' }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: '#94a3b8', font: { size: 11 } } }
          },
          scales: {
            x: { stacked: true, ticks: { color: '#94a3b8' }, grid: { display: false } },
            y: { stacked: true, ticks: { color: '#94a3b8', precision: 0 }, grid: { color: '#1e293b' } }
          }
        }
      });
    }

    function highlightText(text) {
      if (!text) return '';
      return text
        .replace(/(\$[A-Z]{1,5}\b)/g, '<span class="text-cyan-400 font-semibold">$1</span>')
        .replace(/(https?:\\/\\/[^\\s]+)/g, '<a href="$1" target="_blank" class="text-cyan-500 hover:underline break-all">$1</a>');
    }

    async function translateTweet(index, rawText) {
      const transEl = document.getElementById(`trans-text-${index}`);
      const btnEl = document.getElementById(`trans-btn-${index}`);
      if (!transEl) return;

      if (clientTranslations[rawText]) {
        transEl.innerHTML = highlightText(clientTranslations[rawText]);
        transEl.classList.remove('hidden');
        if (btnEl) btnEl.style.display = 'none';
        return;
      }

      if (btnEl) btnEl.innerText = '翻譯中...';
      try {
        const url = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-TW&dt=t&q=' + encodeURIComponent(rawText);
        const res = await fetch(url);
        const json = await res.json();
        const translated = json[0].map(item => item[0]).join('');
        clientTranslations[rawText] = translated;
        localStorage.setItem('serenity_trans_cache', JSON.stringify(clientTranslations));
        transEl.innerHTML = highlightText(translated);
        transEl.classList.remove('hidden');
        if (btnEl) btnEl.style.display = 'none';
      } catch (err) {
        if (btnEl) btnEl.innerText = '翻譯失敗，重試';
      }
    }

    function applyFilters() {
      const query = document.getElementById('search-input').value.trim().toLowerCase();
      const sentiment = document.getElementById('sentiment-filter').value;
      const sort = document.getElementById('sort-order').value;

      filteredTweets = ALL_TWEETS.filter(item => {
        const matchesQuery = !query || 
          item.text.toLowerCase().includes(query) || 
          (item.translation_zh && item.translation_zh.toLowerCase().includes(query)) ||
          item.tickers.some(t => ('$' + t.toLowerCase()).includes(query) || t.toLowerCase().includes(query));
        const matchesSentiment = sentiment === 'ALL' || item.sentiment === sentiment;
        return matchesQuery && matchesSentiment;
      });

      if (sort === 'likes') {
        filteredTweets.sort((a, b) => b.likes - a.likes);
      } else if (sort === 'retweets') {
        filteredTweets.sort((a, b) => b.retweets - a.retweets);
      } else {
        filteredTweets.sort((a, b) => (b.time > a.time ? 1 : -1));
      }

      document.getElementById('filtered-count').innerText = filteredTweets.length.toLocaleString();
      currentPage = 1;
      renderFeed();
    }

    function renderFeed() {
      const feed = document.getElementById('tweets-feed');
      if (currentPage === 1) {
        feed.innerHTML = '';
      }

      const slice = filteredTweets.slice(0, currentPage * PAGE_SIZE);
      const toAppend = filteredTweets.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

      if (slice.length === 0) {
        feed.innerHTML = '<div class="text-center py-16 text-slate-500 text-sm">找不到符合條件的推文</div>';
        document.getElementById('load-more-btn').style.display = 'none';
        return;
      }

      toAppend.forEach((item, idx) => {
        const globalIdx = (currentPage - 1) * PAGE_SIZE + idx;
        const card = document.createElement('div');
        card.className = "bg-cardDark border border-cardBorder p-5 rounded-xl transition hover:border-slate-600 space-y-3";
        
        let badgeColor = "bg-slate-800 text-slate-400 border-slate-700";
        if (item.sentiment === 'Bullish') badgeColor = "bg-emerald-950/60 text-emerald-400 border-emerald-800/60";
        if (item.sentiment === 'Bearish') badgeColor = "bg-rose-950/60 text-rose-400 border-rose-800/60";

        const aiTag = item.is_ai ? '<span class="text-[10px] bg-purple-950/80 text-purple-300 border border-purple-800/60 px-1.5 py-0.5 rounded font-mono">✨ Gemini AI</span>' : '';
        const summaryHtml = item.summary ? `<div class="text-xs text-slate-300 bg-slate-900/90 border border-slate-800 p-2.5 rounded-lg"><span class="text-purple-400 font-semibold">觀點摘要：</span>${item.summary}</div>` : '';

        let contentHtml = '';
        if (item.translation_zh) {
          contentHtml = `
            <div class="text-slate-100 text-sm leading-relaxed whitespace-pre-wrap font-medium">${highlightText(item.translation_zh)}</div>
            <div class="text-slate-400 text-xs leading-relaxed whitespace-pre-wrap border-l-2 border-slate-700 pl-3 pt-1">${highlightText(item.text)}</div>
          `;
        } else {
          const cachedClient = clientTranslations[item.text];
          contentHtml = `
            <div id="trans-text-${globalIdx}" class="text-slate-100 text-sm leading-relaxed whitespace-pre-wrap font-medium ${cachedClient ? '' : 'hidden'}">${cachedClient ? highlightText(cachedClient) : ''}</div>
            <div class="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">${highlightText(item.text)}</div>
            ${cachedClient ? '' : `<button id="trans-btn-${globalIdx}" onclick="translateTweet(${globalIdx}, decodeURIComponent('${encodeURIComponent(item.text)}'))" class="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 mt-1 transition">🌐 翻譯為繁體中文</button>`}
          `;
        }

        const tickerTags = item.tickers.map(t => 
          `<button onclick="selectTicker('${t}')" class="bg-cyan-950/50 hover:bg-cyan-900/60 text-cyan-300 text-xs px-2 py-0.5 rounded border border-cyan-800/50 font-mono font-medium transition cursor-pointer">$${t}</button>`
        ).join(" ");

        const tweetUrl = item.id ? `https://x.com/aleabitoreddit/status/${item.id}` : '#';

        card.innerHTML = `
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-xs px-2.5 py-0.5 rounded-full border font-semibold ${badgeColor}">
                ${item.sentiment}
              </span>
              ${aiTag}
              ${tickerTags}
            </div>
            <a href="${tweetUrl}" target="_blank" class="text-slate-400 hover:text-cyan-400 text-xs flex items-center gap-1.5 transition">
              <span>🕒 ${item.time}</span>
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
            </a>
          </div>
          ${summaryHtml}
          ${contentHtml}
          <div class="flex items-center gap-5 pt-2 text-xs text-slate-400 border-t border-cardBorder/60">
            <span class="flex items-center gap-1">❤️ ${item.likes.toLocaleString()}</span>
            <span class="flex items-center gap-1">🔁 ${item.retweets.toLocaleString()}</span>
            ${item.views > 0 ? `<span class="flex items-center gap-1">👁️ ${item.views.toLocaleString()}</span>` : ''}
          </div>
        `;
        feed.appendChild(card);
      });

      const loadMoreBtn = document.getElementById('load-more-btn');
      loadMoreBtn.style.display = slice.length >= filteredTweets.length ? 'none' : 'inline-block';
    }

    document.getElementById('search-input').addEventListener('input', () => {
      const val = document.getElementById('search-input').value.trim().toUpperCase();
      if (val.startsWith('$')) {
        const sym = val.replace('$', '');
        if (TOP_TICKERS.some(t => t[0] === sym)) {
          renderTickerAnalytics(sym);
        }
      }
      applyFilters();
    });

    document.getElementById('sentiment-filter').addEventListener('change', applyFilters);
    document.getElementById('sort-order').addEventListener('change', applyFilters);
    document.getElementById('load-more-btn').addEventListener('click', () => {
      currentPage++;
      renderFeed();
    });

    applyFilters();
  </script>
</body>
</html>
"""

def generate_html(tweets, ticker_counts):
    total_tweets = len(tweets)
    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:35]
    bull_count = sum(1 for t in tweets if t["sentiment"] == "Bullish")
    bear_count = sum(1 for t in tweets if t["sentiment"] == "Bearish")
    
    tweets_json_str = json.dumps(tweets, ensure_ascii=False)
    top_tickers_json = json.dumps(top_tickers, ensure_ascii=False)

    html = HTML_TEMPLATE
    html = html.replace("__UPDATE_TIME__", datetime.now().strftime('%Y-%m-%d %H:%M'))
    html = html.replace("__TOTAL_TWEETS__", f"{total_tweets:,}")
    html = html.replace("__TICKER_COUNT__", f"{len(ticker_counts):,}")
    html = html.replace("__BULL_COUNT__", f"{bull_count:,}")
    html = html.replace("__BEAR_COUNT__", f"{bear_count:,}")
    html = html.replace("__TWEETS_JSON__", tweets_json_str)
    html = html.replace("__TOP_TICKERS_JSON__", top_tickers_json)

    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 儀表板成功產出至 {OUTPUT_HTML}")

if __name__ == "__main__":
    tweets_raw = load_json(TWEETS_FILE, [])
    sentiment_cache = load_json(CACHE_FILE, {})
    cleaned_tweets, counts = clean_tweet_data(tweets_raw, sentiment_cache)
    generate_html(cleaned_tweets, counts)
