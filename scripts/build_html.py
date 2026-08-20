CACHE_FILE = "data/sentiment_cache.json"
OUTPUT_HTML = "docs/index.html"

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data = data.get("tweets", data.get("data", list(data.values())))
def load_tweets(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
return data
        except Exception as e:
            print(f"讀取 {filepath} 失敗: {e}")
            return default
    return default
            elif isinstance(data, dict):
                for key in ["tweets", "data", "statuses", "results"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return list(data.values())
            return []
    except Exception as e:
        print(f"讀取推文失敗: {e}")
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
        print(f"讀取快取失敗: {e}")
        return {}

def extract_tickers(text):
if not text:
@@ -54,8 +80,8 @@ def extract_tweet_text(item):
for k in ["text", "rawContent", "full_text", "content", "tweet", "body", "message"]:
if k in item and item[k]:
return str(item[k])
    legacy = item.get("legacy") or {}
    if isinstance(legacy, dict) and "full_text" in legacy:
    legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
    if "full_text" in legacy:
return str(legacy["full_text"])
return ""

@@ -66,16 +92,16 @@ def parse_date(item):
raw_date = item[k]
break
if not raw_date:
        legacy = item.get("legacy") or {}
        if isinstance(legacy, dict):
            raw_date = legacy.get("created_at")
        legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
        raw_date = legacy.get("created_at")

if not raw_date:
return "未知時間", "未知月份"

if isinstance(raw_date, (int, float)):
try:
            dt = datetime.fromtimestamp(raw_date / 1000.0 if raw_date > 1e11 else raw_date)
            val = float(raw_date)
            dt = datetime.fromtimestamp(val / 1000.0 if val > 1e11 else val)
return dt.strftime("%Y-%m-%d %H:%M"), dt.strftime("%Y-%m")
except Exception:
pass
@@ -117,17 +143,22 @@ def parse_date(item):

def extract_metrics(item):
likes, retweets, views = 0, 0, 0
    containers = [item, item.get("public_metrics"), item.get("metrics"), item.get("stats"), item.get("legacy")]
    containers = [item]
    for sub in ["public_metrics", "metrics", "stats", "legacy"]:
        val = item.get(sub)
        if isinstance(val, dict):
            containers.append(val)

def get_num(d, keys):
if not isinstance(d, dict): return None
for k in keys:
            if k in d and d[k] is not None and str(d[k]).isdigit():
                return int(d[k])
            if k in d and d[k] is not None:
                val_str = str(d[k]).strip()
                if val_str.isdigit():
                    return int(val_str)
return None

for c in containers:
        if not isinstance(c, dict): continue
if likes == 0:
val = get_num(c, ["likeCount", "likes", "like_count", "favorite_count", "favorites", "favoriteCount", "favs"])
if val is not None: likes = val
@@ -141,6 +172,18 @@ def get_num(d, keys):
return likes, retweets, views

def clean_tweet_data(raw_tweets, sentiment_cache):
    # 防禦性檢查：保證 sentiment_cache 為 dict
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

@@ -155,7 +198,7 @@ def clean_tweet_data(raw_tweets, sentiment_cache):
likes, retweets, views = extract_metrics(item)

ai_data = sentiment_cache.get(tweet_id) if tweet_id else None
        if ai_data:
        if ai_data and isinstance(ai_data, dict):
sentiment = ai_data.get("sentiment", "Neutral")
summary = ai_data.get("summary", "")
translation_zh = ai_data.get("translation_zh", "")
@@ -463,11 +506,13 @@ def clean_tweet_data(raw_tweets, sentiment_cache):
       .replace(/(https?:\\/\\/[^\\s]+)/g, '<a href="$1" target="_blank" class="text-cyan-500 hover:underline break-all">$1</a>');
   }

    async function translateTweet(index, rawText) {
      const transEl = document.getElementById(`trans-text-${index}`);
      const btnEl = document.getElementById(`trans-btn-${index}`);
      if (!transEl) return;
    async function translateByIndex(idx) {
      const transEl = document.getElementById(`trans-text-${idx}`);
      const btnEl = document.getElementById(`trans-btn-${idx}`);
      const item = filteredTweets[idx];
      if (!transEl || !item) return;

      const rawText = item.text;
     if (clientTranslations[rawText]) {
       transEl.innerHTML = highlightText(clientTranslations[rawText]);
       transEl.classList.remove('hidden');
@@ -480,7 +525,7 @@ def clean_tweet_data(raw_tweets, sentiment_cache):
       const url = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-TW&dt=t&q=' + encodeURIComponent(rawText);
       const res = await fetch(url);
       const json = await res.json();
        const translated = json[0].map(item => item[0]).join('');
        const translated = json[0].map(row => row[0]).join('');
       clientTranslations[rawText] = translated;
       localStorage.setItem('serenity_trans_cache', JSON.stringify(clientTranslations));
       transEl.innerHTML = highlightText(translated);
@@ -556,7 +601,7 @@ def clean_tweet_data(raw_tweets, sentiment_cache):
         contentHtml = `
           <div id="trans-text-${globalIdx}" class="text-slate-100 text-sm leading-relaxed whitespace-pre-wrap font-medium ${cachedClient ? '' : 'hidden'}">${cachedClient ? highlightText(cachedClient) : ''}</div>
           <div class="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">${highlightText(item.text)}</div>
            ${cachedClient ? '' : `<button id="trans-btn-${globalIdx}" onclick="translateTweet(${globalIdx}, decodeURIComponent('${encodeURIComponent(item.text)}'))" class="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 mt-1 transition">🌐 翻譯為繁體中文</button>`}
            ${cachedClient ? '' : `<button id="trans-btn-${globalIdx}" onclick="translateByIndex(${globalIdx})" class="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 mt-1 transition">🌐 翻譯為繁體中文</button>`}
         `;
       }

@@ -643,7 +688,7 @@ def generate_html(tweets, ticker_counts):
print(f"✅ 儀表板成功產出至 {OUTPUT_HTML}")

if __name__ == "__main__":
    tweets_raw = load_json(TWEETS_FILE, [])
    sentiment_cache = load_json(CACHE_FILE, {})
    tweets_raw = load_tweets(TWEETS_FILE)
    sentiment_cache = load_cache(CACHE_FILE)
cleaned_tweets, counts = clean_tweet_data(tweets_raw, sentiment_cache)
generate_html(cleaned_tweets, counts)
