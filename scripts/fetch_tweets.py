import json
import os
import re
import sys
import time
from datetime import datetime
import requests

# ==========================================
# 參數設定區 (Serenity Tracker: aleabitoreddit)
# ==========================================
TARGET_HANDLE = "aleabitoreddit"
OUTPUT_FILE = "data/tweets.json"
ALT_OUTPUT_FILE = "data/aleabitoreddit_tweets.json"

# 偽裝瀏覽器標頭，避免 GitHub Actions 伺服器 IP 被 Twitter 封鎖
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
    "Referer": f"https://twitter.com/{TARGET_HANDLE}",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

def load_existing_tweets():
    """讀取既有的歷史推文資料，確保合併時不遺失任何歷史推文"""
    for path in [OUTPUT_FILE, ALT_OUTPUT_FILE]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        print(f"📖 成功讀取既有推文庫 ({path})：共 {len(data)} 則", flush=True)
                        return data
                    elif isinstance(data, dict):
                        for k in ["tweets", "data", "statuses", "results"]:
                            if k in data and isinstance(data[k], list):
                                return data[k]
                        return list(data.values())
            except Exception as e:
                print(f"⚠️ 讀取歷史檔案失敗 ({path}): {e}", flush=True)
    return []

def fetch_syndication_timeline(handle):
    """通道 1：透過 Twitter 官方 Syndication Profile 抓取最新即時貼文"""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
    tweets = []
    try:
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        if res.status_code == 200:
            # 從回傳的 HTML / JSON 混合字串中提取 __NEXT_DATA__
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text, re.DOTALL)
            if match:
                json_data = json.loads(match.group(1))
                entries = (
                    json_data.get("props", {})
                    .get("pageProps", {})
                    .get("timeline", {})
                    .get("entries", [])
                )
                for entry in entries:
                    content = entry.get("content", {})
                    tweet_data = content.get("tweet", {})
                    if tweet_data:
                        tweets.append(tweet_data)
                print(f"✅ [通道 1] 成功自 Syndication 時間軸取得 {len(tweets)} 則近期推文", flush=True)
                return tweets
            else:
                print("⚠️ [通道 1] 未能匹配到 __NEXT_DATA__ 結構，準備切換備援通道...", flush=True)
        else:
            print(f"⚠️ [通道 1] 回傳狀態碼異常: {res.status_code}", flush=True)
    except Exception as e:
        print(f"⚠️ [通道 1] 連線失敗: {e}", flush=True)
    return tweets

def fetch_cdn_widget_tweets(handle):
    """通道 2：備援 CDN Widget 端點"""
    url = f"https://cdn.syndication.twimg.com/widgets/followbutton/info.json?screen_names={handle}"
    tweets = []
    try:
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0 and "status" in data[0]:
                tweets.append(data[0]["status"])
                print("✅ [通道 2] 成功自 Widget 端點取得最新推文", flush=True)
    except Exception as e:
        print(f"⚠️ [通道 2] 連線失敗: {e}", flush=True)
    return tweets

def normalize_tweet_item(raw_tweet):
    """將推文統一正規化為標準字典結構"""
    if not isinstance(raw_tweet, dict):
        return None

    # 提取 ID
    t_id = (
        raw_tweet.get("id_str")
        or str(raw_tweet.get("id") or "")
        or str(raw_tweet.get("tweet_id") or "")
    )
    if not t_id or t_id == "0":
        return None

    # 提取內文
    text = (
        raw_tweet.get("text")
        or raw_tweet.get("full_text")
        or raw_tweet.get("rawContent")
        or ""
    )
    if not text:
        legacy = raw_tweet.get("legacy")
        if isinstance(legacy, dict):
            text = legacy.get("full_text") or ""
    if not text:
        return None

    # 提取時間
    created_at = (
        raw_tweet.get("created_at")
        or raw_tweet.get("createdAt")
        or raw_tweet.get("date")
        or ""
    )
    
    # 若原始資料無標準時間，利用 Snowflake 演算法還原發布時間
    if (not created_at or created_at.startswith("1970")) and t_id.isdigit() and len(t_id) >= 10:
        try:
            ts_ms = (int(t_id) >> 22) + 1288834974657
            dt = datetime.utcfromtimestamp(ts_ms / 1000.0)
            created_at = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    # 提取互動數據
    likes = raw_tweet.get("favorite_count") or raw_tweet.get("likes") or 0
    retweets = raw_tweet.get("retweet_count") or raw_tweet.get("retweets") or 0
    views = raw_tweet.get("views") or 0
    if isinstance(views, dict):
        views = views.get("count", 0)

    url = f"https://twitter.com/{TARGET_HANDLE}/status/{t_id}"

    return {
        "id": t_id,
        "id_str": t_id,
        "text": text,
        "created_at": created_at,
        "favorite_count": int(likes) if str(likes).isdigit() else 0,
        "retweet_count": int(retweets) if str(retweets).isdigit() else 0,
        "views": int(views) if str(views).isdigit() else 0,
        "url": url,
    }

def main():
    print(f"🚀 開始抓取 @{TARGET_HANDLE} 最新推特貼文...", flush=True)
    
    existing_tweets = load_existing_tweets()
    existing_map = {}
    for item in existing_tweets:
        if isinstance(item, dict):
            t_id = str(item.get("id") or item.get("id_str") or item.get("tweet_id") or "")
            if t_id:
                existing_map[t_id] = item

    # 依序調用通道抓取最新推文
    new_raw_tweets = fetch_syndication_timeline(TARGET_HANDLE)
    if not new_raw_tweets:
        print("🔄 主通道未能獲取推文，嘗試備援通道...", flush=True)
        new_raw_tweets = fetch_cdn_widget_tweets(TARGET_HANDLE)

    added_count = 0
    for raw in new_raw_tweets:
        normalized = normalize_tweet_item(raw)
        if normalized:
            t_id = normalized["id"]
            if t_id not in existing_map:
                existing_map[t_id] = normalized
                added_count += 1
            else:
                # 更新最新的互動數據（按讚/轉發）
                existing_map[t_id]["favorite_count"] = max(
                    existing_map[t_id].get("favorite_count", 0), normalized.get("favorite_count", 0)
                )
                existing_map[t_id]["retweet_count"] = max(
                    existing_map[t_id].get("retweet_count", 0), normalized.get("retweet_count", 0)
                )

    total_tweets = list(existing_map.values())

    # 排序：依時間由新至舊排列
    def get_sort_key(item):
        t_id = str(item.get("id") or item.get("id_str") or "0")
        created = str(item.get("created_at") or "")
        return (created, t_id)

    total_tweets.sort(key=get_sort_key, reverse=True)

    # 確保輸出目錄存在並寫入檔案
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(total_tweets, f, ensure_ascii=False, indent=2)

    with open(ALT_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(total_tweets, f, ensure_ascii=False, indent=2)

    print(f"🎉 推文更新完成！", flush=True)
    print(f"   • 本次新增推文數：{added_count} 則", flush=True)
    print(f"   • 資料庫總推文數：{len(total_tweets)} 則", flush=True)
    if len(total_tweets) > 0:
        latest = total_tweets[0]
        print(f"   • 最新推文發布時間：{latest.get('created_at')} (ID: {latest.get('id')})", flush=True)
        print(f"   • 最新推文摘要：{latest.get('text', '')[:60]}...", flush=True)

if __name__ == "__main__":
    main()
