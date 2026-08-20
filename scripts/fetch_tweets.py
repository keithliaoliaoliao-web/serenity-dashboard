import json
import os
import re
import time
import urllib.request
from datetime import datetime

TARGET_HANDLE = "aleabitoreddit"
TWEETS_FILE = "data/tweets.json"

AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
CT0 = os.environ.get("TWITTER_CT0", "").strip()

def log(message):
    """強制即時輸出日誌"""
    print(message, flush=True)

def load_existing_tweets(filepath):
    """讀取現有推文資料庫"""
    if not os.path.exists(filepath):
        log("ℹ️ 本地 tweets.json 不存在，將建立新資料庫。")
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        log(f"⚠️ 讀取現有推文失敗: {e}")
        return []

def normalize_iso_date(date_str):
    """將各類日期字串統一轉為標準 ISO 8601 格式以利排序"""
    if not date_str:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    date_str = str(date_str).strip()
    
    # 支援 Twitter 標準格式: 'Thu Aug 20 08:30:00 +0000 2026'
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass

    # 支援 'YYYY-MM-DD HH:MM:SS' 或 'YYYY-MM-DD HH:MM'
    try:
        if "T" not in date_str:
            clean = date_str.replace("/", "-")
            if len(clean) == 16:
                dt = datetime.strptime(clean, "%Y-%m-%d %H:%M")
            else:
                dt = datetime.strptime(clean[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass

    return date_str

def fetch_syndication_stream(screen_name):
    """軌道 1：官方 Syndication 串流（加入動態防快取時間戳記）"""
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

    fetched = []
    log(f"📡 [軌道 1] 正在連線 Twitter 官方串流抓取 @{screen_name} 最新發文...")

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8")

            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>', html)
            if not match:
                log("⚠️ 未能解析出 JSON 區塊。")
                return []

            data = json.loads(match.group(1))
            entries = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])

            for entry in entries:
                tweet_raw = entry.get("content", {}).get("tweet")
                if not tweet_raw:
                    continue

                tweet_id = str(tweet_raw.get("id_str") or tweet_raw.get("id", "")).strip()
                text = tweet_raw.get("full_text") or tweet_raw.get("text", "")
                created_at = normalize_iso_date(tweet_raw.get("created_at", ""))
                fav_count = tweet_raw.get("favorite_count", 0)
                rt_count = tweet_raw.get("retweet_count", 0)
                views_data = tweet_raw.get("views", {})
                views = views_data.get("count", 0) if isinstance(views_data, dict) else (tweet_raw.get("views", 0) or 0)

                if tweet_id and text:
                    fetched.append({
                        "id": tweet_id,
                        "text": text.strip(),
                        "created_at": created_at,
                        "favorite_count": int(fav_count),
                        "retweet_count": int(rt_count),
                        "views": int(views) if str(views).isdigit() else 0,
                        "url": f"https://twitter.com/{screen_name}/status/{tweet_id}"
                    })

            log(f"✨ [軌道 1] 解析出 {len(fetched)} 則推文！")

    except Exception as e:
        log(f"⚠️ [軌道 1 異常]: {e}")

    return fetched

def fetch_fxtwitter_backup(screen_name):
    """軌道 2：FxTwitter 開放節點（補充最新回覆與動態）"""
    url = f"https://api.fxtwitter.com/{screen_name}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    fetched = []
    log(f"🔍 [軌道 2] 正在透過 FxTwitter 備援節點檢索最新發文...")

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            # 安全取得單篇或列表推文
            raw_tweets = []
            if isinstance(data, dict):
                if isinstance(data.get("tweets"), list):
                    raw_tweets = data["tweets"]
                elif isinstance(data.get("tweet"), dict):
                    raw_tweets = [data["tweet"]]

            for tw in raw_tweets:
                if not isinstance(tw, dict):
                    continue
                t_id = str(tw.get("id") or tw.get("id_str") or "").strip()
                text = tw.get("text") or tw.get("full_text") or ""
                created_at = normalize_iso_date(tw.get("created_at") or tw.get("created_timestamp"))
                
                if t_id and text:
                    fetched.append({
                        "id": t_id,
                        "text": text.strip(),
                        "created_at": created_at,
                        "favorite_count": int(tw.get("likes", 0) or tw.get("favorite_count", 0)),
                        "retweet_count": int(tw.get("retweets", 0) or tw.get("retweet_count", 0)),
                        "views": int(tw.get("views", 0)),
                        "url": f"https://twitter.com/{screen_name}/status/{t_id}"
                    })

            log(f"✨ [軌道 2] 解析出 {len(fetched)} 則備援推文！")

    except Exception as e:
        log(f"⚠️ [軌道 2 異常]: {e}")

    return fetched

def save_merged_tweets(filepath, new_tweets):
    """比對去重並更新本地推文資料庫"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    existing_tweets = load_existing_tweets(filepath)

    tweets_map = {str(t.get("id", "")).strip(): t for t in existing_tweets if t.get("id")}

    added_count = 0
    updated_count = 0

    for t in new_tweets:
        t_id = str(t.get("id", "")).strip()
        if not t_id:
            continue

        if t_id not in tweets_map:
            tweets_map[t_id] = t
            added_count += 1
            log(f"  ➕ 發現新推文 [{t_id}]: {t['created_at']} | {t['text'][:35]}...")
        else:
            tweets_map[t_id] = t
            updated_count += 1

    merged_list = list(tweets_map.values())
    
    # 嚴格按時間降序排序（最新發布排在最前面）
    merged_list.sort(key=lambda x: normalize_iso_date(x.get("created_at", "") or x.get("date", "")), reverse=True)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, ensure_ascii=False, indent=2)

    log(
        f"📊 [結算報告] 本次抓取: {len(new_tweets)} 則 | "
        f"全新新增: {added_count} 則 | "
        f"既有推文更新: {updated_count} 則 | "
        f"目前推文資料庫總數: {len(merged_list)} 則"
    )

    if merged_list:
        latest = merged_list[0]
        log(f"🔝 資料庫最新第一筆推文日期: {latest.get('created_at')} (ID: {latest.get('id')})")

if __name__ == "__main__":
    log(f"🚀 開始執行 @{TARGET_HANDLE} 推文擷取流程...")
    
    # 1. 執行官方串流（附帶防快取戳記）
    tweets = fetch_syndication_stream(TARGET_HANDLE)
    
    # 2. 備援補強
    backup_tweets = fetch_fxtwitter_backup(TARGET_HANDLE)
    all_incoming = tweets + backup_tweets
    
    save_merged_tweets(TWEETS_FILE, all_incoming)
    log("✅ 推文擷取任務執行完畢。")
