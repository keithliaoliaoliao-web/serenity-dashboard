import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime

# ==========================================
# 參數設定區 (Serenity 專案)
# ==========================================
TARGET_HANDLE = "aleabitoreddit"
TWEETS_FILE = "data/tweets.json"

# Yan Labs 儲存庫候選路徑
YAN_LABS_CANDIDATE_URLS = [
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/master/data/tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/master/tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/gh-pages/data/tweets.json",
]

AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
CT0 = os.environ.get("TWITTER_CT0", "").strip()
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_PAT", "").strip()

# Twitter Snowflake 紀元常數
TWITTER_EPOCH = 1288834974657

def log(message):
    """即時輸出日誌至控制台"""
    print(message, flush=True)

def snowflake_to_iso(tweet_id_str):
    """利用 Twitter Snowflake 演算法反推精確 UTC 發布時間"""
    try:
        t_id = int(str(tweet_id_str).strip())
        timestamp_ms = (t_id >> 22) + TWITTER_EPOCH
        dt = datetime.utcfromtimestamp(timestamp_ms / 1000.0)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None

def load_local_tweets(filepath):
    """讀取本地既有推文資料庫"""
    if not os.path.exists(filepath):
        log("ℹ️ 本地 tweets.json 尚不存在，將建立新檔案。")
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []

            cleaned = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                t_id = str(item.get("id") or item.get("id_str") or "").strip()
                if not t_id.isdigit() or len(t_id) < 10:
                    continue

                item["id"] = t_id
                item["created_at"] = snowflake_to_iso(t_id) or item.get("created_at") or "1970-01-01T00:00:00Z"
                cleaned.append(item)

            return cleaned
    except Exception as e:
        log(f"⚠️ 讀取本地推文失敗: {e}")
        return []

def fetch_yan_labs_data():
    """【軌道 1】帶 Token 探測 Yan Labs 遠端資料庫"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"

    log(f"🌐 [軌道 1] 正在連線探測 Yan Labs (yan-labs/serenity-aleabitoreddit)...")

    for url in YAN_LABS_CANDIDATE_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    
                    raw_list = []
                    if isinstance(raw_data, list):
                        raw_list = raw_data
                    elif isinstance(raw_data, dict):
                        for k in ["tweets", "data", "statuses"]:
                            if isinstance(raw_data.get(k), list):
                                raw_list = raw_data[k]
                                break
                        if not raw_list:
                            raw_list = list(raw_data.values())

                    cleaned = []
                    for item in raw_list:
                        if not isinstance(item, dict):
                            continue
                        t_id = str(item.get("id") or item.get("id_str") or "").strip()
                        text = item.get("text") or item.get("full_text") or item.get("content") or ""
                        
                        if t_id.isdigit() and len(t_id) >= 10 and text:
                            cleaned.append({
                                "id": t_id,
                                "text": text.strip(),
                                "created_at": snowflake_to_iso(t_id) or item.get("created_at") or "1970-01-01T00:00:00Z",
                                "favorite_count": int(item.get("favorite_count", 0) or item.get("likes", 0) or 0),
                                "retweet_count": int(item.get("retweet_count", 0) or item.get("retweets", 0) or 0),
                                "views": int(item.get("views", 0) or 0),
                                "url": item.get("url") or f"https://twitter.com/{TARGET_HANDLE}/status/{t_id}",
                                "source": "yan_labs"
                            })

                    log(f"  ✨ [軌道 1] 成功連線並自 {url} 同步 {len(cleaned)} 則推文！")
                    return cleaned
        except urllib.error.HTTPError as he:
            log(f"  ↳ 探測 {url.split('/')[-2]}/{url.split('/')[-1]} -> HTTP {he.code}")
        except Exception as e:
            log(f"  ↳ 探測異常: {e}")

    log("  ℹ️ Yan Labs 候選路徑未取得資料，自動使用本地既有資料庫與官方即時串流。")
    return []

def fetch_syndication_stream(screen_name):
    """【軌道 2】Twitter 官方認證即時串流"""
    timestamp = int(time.time())
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{screen_name}?t={timestamp}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://platform.twitter.com/"
    }

    if AUTH_TOKEN and CT0:
        headers["Cookie"] = f"auth_token={AUTH_TOKEN}; ct0={CT0};"
        headers["x-csrf-token"] = CT0
        log("🔑 官方認證憑證 (Cookies) 注入成功。")

    fetched = []
    user_id = None
    log(f"📡 [軌道 2] 正在連線 Twitter 官方串流抓取 @{screen_name} 本地最新即時發文...")

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8")

            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>', html)
            if match:
                data = json.loads(match.group(1))
                entries = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])

                for entry in entries:
                    tw = entry.get("content", {}).get("tweet")
                    if not tw:
                        continue

                    if not user_id and tw.get("user", {}).get("id_str"):
                        user_id = str(tw["user"]["id_str"]).strip()

                    tweet_id = str(tw.get("id_str") or tw.get("id", "")).strip()
                    text = tw.get("full_text") or tw.get("text", "")
                    created_at = snowflake_to_iso(tweet_id) or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

                    fav_count = int(tw.get("favorite_count", 0) or 0)
                    rt_count = int(tw.get("retweet_count", 0) or 0)
                    views_data = tw.get("views", {})
                    views = int(views_data.get("count", 0)) if isinstance(views_data, dict) and str(views_data.get("count", "")).isdigit() else 0

                    if tweet_id and text:
                        fetched.append({
                            "id": tweet_id,
                            "text": text.strip(),
                            "created_at": created_at,
                            "favorite_count": fav_count,
                            "retweet_count": rt_count,
                            "views": views,
                            "url": f"https://twitter.com/{screen_name}/status/{tweet_id}",
                            "source": "live_stream"
                        })

                log(f"  ✨ [軌道 2] 官方串流成功解析出 {len(fetched)} 則即時推文！")
    except Exception as e:
        log(f"  ⚠️ [軌道 2 異常]: {e}")

    return user_id, fetched

def enrich_recent_metrics(tweets_list, target_count=40):
    """【軌道 3】強制同步前 40 則推文的真實按讚數、轉推數與瀏覽量"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    updated = 0
    check_limit = min(len(tweets_list), target_count)
    log(f"🔄 [數據校準] 正在為最新 {check_limit} 則推文連線同步真實互動指標 (❤️ / 🔁 / 👁️)...")

    for tw in tweets_list[:check_limit]:
        t_id = str(tw.get("id", "")).strip()
        if not t_id.isdigit() or len(t_id) < 10:
            continue

        api_url = f"https://api.fxtwitter.com/status/{t_id}"
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    t_data = data.get("tweet", {})
                    if t_data:
                        likes = int(t_data.get("likes", 0) or t_data.get("favorite_count", 0) or 0)
                        retweets = int(t_data.get("retweets", 0) or t_data.get("retweet_count", 0) or 0)
                        views = int(t_data.get("views", 0) or 0)

                        tw["favorite_count"] = likes
                        tw["retweet_count"] = retweets
                        tw["views"] = views

                        if t_data.get("text") and len(t_data["text"]) > len(tw.get("text", "")):
                            tw["text"] = t_data["text"]

                        updated += 1
            time.sleep(0.1)
        except Exception:
            continue

    log(f"✨ 成功校準 {updated} 則推文的真實互動指標！")
    return tweets_list

def merge_and_compare_sources(local_data, yan_labs_data, live_stream_data):
    """三軌資料合併去重與時間校準"""
    tweets_map = {}

    for tw in local_data:
        t_id = str(tw.get("id", "")).strip()
        if t_id:
            tweets_map[t_id] = tw

    local_count = len(tweets_map)
    yan_added = 0
    live_added = 0

    for tw in yan_labs_data:
        t_id = str(tw.get("id", "")).strip()
        if not t_id:
            continue
        if t_id not in tweets_map:
            tweets_map[t_id] = tw
            yan_added += 1
        else:
            if len(tw.get("text", "")) > len(tweets_map[t_id].get("text", "")):
                tweets_map[t_id]["text"] = tw["text"]

    for tw in live_stream_data:
        t_id = str(tw.get("id", "")).strip()
        if not t_id:
            continue
        if t_id not in tweets_map:
            tweets_map[t_id] = tw
            live_added += 1
            log(f"  ➕ [即時捕獲新貼文] [{t_id}] ({tw['created_at']}): {tw['text'][:35]}...")
        else:
            old = tweets_map[t_id]
            if tw.get("favorite_count", 0) >= old.get("favorite_count", 0):
                tweets_map[t_id]["favorite_count"] = tw["favorite_count"]
            if tw.get("retweet_count", 0) >= old.get("retweet_count", 0):
                tweets_map[t_id]["retweet_count"] = tw["retweet_count"]
            if tw.get("views", 0) >= old.get("views", 0):
                tweets_map[t_id]["views"] = tw["views"]
            if len(tw.get("text", "")) > len(old.get("text", "")):
                tweets_map[t_id]["text"] = tw["text"]

    merged_list = list(tweets_map.values())

    # 嚴格按 Snowflake UTC 時間降序排序
    merged_list.sort(
        key=lambda x: str(x.get("created_at") or snowflake_to_iso(x.get("id")) or "1970-01-01T00:00:00Z"),
        reverse=True
    )

    # 校準前 40 則最新推文的互動數據
    merged_list = enrich_recent_metrics(merged_list, target_count=40)

    log(
        f"📊 [比對結算] 本地既有: {local_count} 則 | "
        f"Yan Labs 增補: {yan_added} 則 | "
        f"即時捕獲新增: {live_added} 則 | "
        f"🎉 融合後資料庫總數: {len(merged_list)} 則"
    )

    return merged_list

def save_tweets(filepath, tweets_list):
    """儲存資料庫檔案"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(tweets_list, f, ensure_ascii=False, indent=2)

    file_size_kb = os.path.getsize(filepath) / 1024.0
    log(f"💾 資料庫已成功寫入 {filepath} (檔案大小: {file_size_kb:.1f} KB)")

    if tweets_list:
        latest = tweets_list[0]
        log(f"🔝 最新第 1 筆推文: {latest.get('created_at')} (ID: {latest.get('id')}) | ❤️ {latest.get('favorite_count', 0)}  🔁 {latest.get('retweet_count', 0)}  👁️ {latest.get('views', 0)}")

if __name__ == "__main__":
    log(f"🚀 開始執行 @{TARGET_HANDLE} (Serenity) 多來源比對融合與即時同步流程...")

    local_tweets = load_local_tweets(TWEETS_FILE)
    yan_tweets = fetch_yan_labs_data()
    user_id, live_tweets = fetch_syndication_stream(TARGET_HANDLE)

    final_merged = merge_and_compare_sources(local_tweets, yan_tweets, live_tweets)
    save_tweets(TWEETS_FILE, final_merged)
    log("✅ 任務全部完成。")
