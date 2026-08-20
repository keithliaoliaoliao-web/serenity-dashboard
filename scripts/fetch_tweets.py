import json
import os
import re
import time
import urllib.request
from datetime import datetime

# 目標推特帳號：Serenity (aleabitoreddit)
TARGET_HANDLE = "aleabitoreddit"
TWEETS_FILE = "data/tweets.json"

AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
CT0 = os.environ.get("TWITTER_CT0", "").strip()

def log(message):
    """即時輸出日誌至控制台"""
    print(message, flush=True)

def robust_parse_date(raw_date):
    """強大相容性日期解析器：精準識別多種時間格式，解析失敗回傳 None"""
    if not raw_date:
        return None
    
    s = str(raw_date).strip()
    if not s or s.lower() in ("none", "null", "1970-01-01t00:00:00z", "1970-01-01 00:00", "未知時間"):
        return None

    # 1. Twitter 官方格式: "Tue Aug 18 14:15:00 +0000 2026"
    try:
        dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass

    # 2. 標準 ISO 格式: "2026-08-20T16:12:00Z" 或 "2026-08-20T16:12:00.000Z"
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', s):
        return s[:19] + "Z"

    # 3. 常見日期格式: "2026-08-18 14:15:00" 或 "2026-08-18 14:15" 或 "2026/08/18"
    try:
        clean = s.replace("/", "-")
        if len(clean) >= 19:
            dt = datetime.strptime(clean[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif len(clean) == 16:
            dt = datetime.strptime(clean, "%Y-%m-%d %H:%M")
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif len(clean) == 10:
            dt = datetime.strptime(clean, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%dT00:00:00Z")
    except Exception:
        pass

    # 4. RFC 2822 格式 (RSS): "Wed, 20 Aug 2026 16:12:00 GMT"
    try:
        clean_rfc = re.sub(r'^[A-Za-z]+,\s*', '', s)
        dt = datetime.strptime(clean_rfc[:20].strip(), "%d %b %Y %H:%M:%S")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass

    # 5. Unix 時間戳 (數字)
    if s.isdigit():
        try:
            ts = int(s)
            dt = datetime.utcfromtimestamp(ts / 1000.0 if ts > 1e11 else ts)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    return None

def recover_tweet_date(item):
    """自我修復：從所有備援欄位中還原正確日期"""
    # 依序檢索所有可能的日期欄位
    candidates = [
        item.get("created_at"),
        item.get("date"),
        item.get("datetime"),
        item.get("timestamp"),
        item.get("time"),
        item.get("pubDate")
    ]
    legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
    candidates.append(legacy.get("created_at"))

    for c in candidates:
        parsed = robust_parse_date(c)
        if parsed and not parsed.startswith("1970"):
            return parsed

    return "1970-01-01T00:00:00Z"

def load_existing_tweets(filepath):
    """讀取本地推文並自動修復先前被誤改為 1970 的舊推文日期"""
    if not os.path.exists(filepath):
        log("ℹ️ 本地 tweets.json 尚不存在，將建立新資料庫。")
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            
            repaired_count = 0
            cleaned = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                t_id = str(item.get("id") or item.get("id_str") or "").strip()
                if not t_id:
                    continue
                
                original_date = item.get("created_at", "")
                recovered_date = recover_tweet_date(item)
                
                if str(original_date).startswith("1970") and not recovered_date.startswith("1970"):
                    repaired_count += 1

                item["created_at"] = recovered_date
                cleaned.append(item)

            if repaired_count > 0:
                log(f"🛠️ [自我修復] 成功修復 {repaired_count} 則歷史推文的 1970 日期異常！")
            return cleaned
    except Exception as e:
        log(f"⚠️ 讀取現有推文失敗: {e}")
        return []

def fetch_tweets_syndication(screen_name):
    """透過 Twitter 官方 Syndication 串流抓取真實推文與完整互動數據"""
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
    else:
        log("⚠️ 未偵測到完整 Cookies，將使用公開訪客模式連線。")

    fetched_tweets = []
    log(f"📡 正在連線 Twitter 官方串流端點抓取 @{screen_name} 最新發文...")

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
                
                # 解析官方發布時間
                raw_time = tweet_raw.get("created_at", "")
                created_at = robust_parse_date(raw_time) or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

                # 解析真實互動數據
                fav_count = int(tweet_raw.get("favorite_count", 0) or 0)
                rt_count = int(tweet_raw.get("retweet_count", 0) or 0)
                views_data = tweet_raw.get("views", {})
                views = int(views_data.get("count", 0)) if isinstance(views_data, dict) and str(views_data.get("count", "")).isdigit() else 0

                if tweet_id and text:
                    fetched_tweets.append({
                        "id": tweet_id,
                        "text": text.strip(),
                        "created_at": created_at,
                        "favorite_count": fav_count,
                        "retweet_count": rt_count,
                        "views": views,
                        "url": f"https://twitter.com/{screen_name}/status/{tweet_id}"
                    })

            log(f"✨ 順利從官方串流解析出 {len(fetched_tweets)} 則真實推文（含愛心/轉推數據）！")

    except Exception as e:
        log(f"⚠️ 官方串流抓取異常: {e}")

    return fetched_tweets

def save_merged_tweets(filepath, new_tweets):
    """將新推文與現有資料庫合併去重，並由新到舊嚴格排序"""
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
            log(f"  ➕ 新增真實推文 [{t_id}] ({t['created_at']}): {t['text'][:35]}...")
        else:
            # 若既有推文數據不完整，或新抓取有更新的愛心數，則進行更新
            old_item = tweets_map[t_id]
            if t.get("favorite_count", 0) > 0 or t.get("views", 0) > 0 or str(old_item.get("created_at", "")).startswith("1970"):
                tweets_map[t_id].update(t)
                updated_count += 1

    merged_list = list(tweets_map.values())

    # 嚴格按 ISO 8601 時間由新到舊排序（1970 沉底）
    merged_list.sort(
        key=lambda x: str(x.get("created_at") or recover_tweet_date(x)), 
        reverse=True
    )

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, ensure_ascii=False, indent=2)

    log(
        f"📊 [結算報告] 本次官方抓取: {len(new_tweets)} 則 | "
        f"全新新增: {added_count} 則 | "
        f"既有資料修復/更新: {updated_count} 則 | "
        f"目前推文資料庫總數: {len(merged_list)} 則"
    )

    if merged_list:
        latest = merged_list[0]
        log(f"🔝 資料庫最新第一筆推文日期: {latest.get('created_at')} (ID: {latest.get('id')})")

if __name__ == "__main__":
    log(f"🚀 開始執行 @{TARGET_HANDLE} 官方認證推文擷取任務...")
    tweets = fetch_tweets_syndication(TARGET_HANDLE)
    save_merged_tweets(TWEETS_FILE, tweets)
    log("✅ 任務全部完成。")
