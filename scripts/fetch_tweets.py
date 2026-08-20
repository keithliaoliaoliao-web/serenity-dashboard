import json
import os
import re
import sys
import urllib.request
from datetime import datetime

# Serenity 目標推特帳號
TARGET_HANDLE = "aleabitoreddit"
TWEETS_FILE = "data/tweets.json"

AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
CT0 = os.environ.get("TWITTER_CT0", "").strip()

def log(message):
    """即時強制輸出日誌至控制台"""
    print(message, flush=True)

def load_existing_tweets(filepath):
    """讀取本地現有推文資料庫"""
    if not os.path.exists(filepath):
        log("ℹ️ 本地 tweets.json 尚不存在，將建立新檔案。")
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        log(f"⚠️ 讀取現有推文失敗: {e}")
        return []

def fetch_tweets_syndication(screen_name):
    """透過 Twitter 官方 Syndication 串流抓取最新推文"""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{screen_name}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://platform.twitter.com/"
    }

    if AUTH_TOKEN and CT0:
        headers["Cookie"] = f"auth_token={AUTH_TOKEN}; ct0={CT0};"
        headers["x-csrf-token"] = CT0
        log("🔑 已成功帶入 Twitter 認證憑證 (Cookies)。")
    else:
        log("⚠️ 未偵測到完整 Cookies，將嘗試以訪客身分發出請求。")

    fetched_tweets = []
    log(f"📡 正在連線官方串流端點抓取 @{screen_name} 最新推文...")

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8")

            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>', html)
            if not match:
                log("⚠️ 未能從頁面中解析出結構化 JSON 資料區塊。")
                return []

            data = json.loads(match.group(1))
            entries = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])

            for entry in entries:
                tweet_raw = entry.get("content", {}).get("tweet")
                if not tweet_raw:
                    continue

                tweet_id = str(tweet_raw.get("id_str") or tweet_raw.get("id", "")).strip()
                text = tweet_raw.get("full_text") or tweet_raw.get("text", "")
                created_at = tweet_raw.get("created_at", "")
                fav_count = tweet_raw.get("favorite_count", 0)
                rt_count = tweet_raw.get("retweet_count", 0)
                views_data = tweet_raw.get("views", {})
                views = views_data.get("count", 0) if isinstance(views_data, dict) else (tweet_raw.get("views", 0) or 0)

                iso_date = ""
                try:
                    dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                    iso_date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    iso_date = str(created_at)

                if tweet_id and text:
                    fetched_tweets.append({
                        "id": tweet_id,
                        "text": text.strip(),
                        "created_at": iso_date,
                        "favorite_count": int(fav_count),
                        "retweet_count": int(rt_count),
                        "views": int(views) if str(views).isdigit() else 0,
                        "url": f"https://twitter.com/{screen_name}/status/{tweet_id}"
                    })

            log(f"✨ 順利從官方串流解析出 {len(fetched_tweets)} 則最新推文！")

    except Exception as e:
        log(f"⚠️ 串流連線發生異常: {e}")

    return fetched_tweets

def save_merged_tweets(filepath, new_tweets):
    """將新推文與現有資料庫合併去重並儲存"""
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
        else:
            tweets_map[t_id] = t
            updated_count += 1

    merged_list = list(tweets_map.values())
    merged_list.sort(key=lambda x: str(x.get("created_at", "") or x.get("date", "")), reverse=True)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, ensure_ascii=False, indent=2)

    log(
        f"📊 [結算報告] 本次抓取: {len(new_tweets)} 則 | "
        f"全新新增: {added_count} 則 | "
        f"既有推文更新: {updated_count} 則 | "
        f"目前推文資料庫總數: {len(merged_list)} 則"
    )

if __name__ == "__main__":
    log(f"🚀 開始執行 @{TARGET_HANDLE} 推文擷取流程...")
    tweets = fetch_tweets_syndication(TARGET_HANDLE)
    save_merged_tweets(TWEETS_FILE, tweets)
    log("✅ 推文擷取任務執行完畢。")
