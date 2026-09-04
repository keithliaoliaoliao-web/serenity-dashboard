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
TWEETS_FILE = "data/tweets.json"
ALT_TWEETS_FILE = "data/aleabitoreddit_tweets.json"

# Yan Labs 官方遠端資料庫候選路徑 (支援 CDN 備援加速)
YAN_LABS_CANDIDATE_URLS = [
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json",
    "https://cdn.jsdelivr.net/gh/yan-labs/serenity-aleabitoreddit@main/data/aleabitoreddit_tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/master/data/aleabitoreddit_tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/tweets.json",
]

# GitHub Actions Secrets 憑證注入 (可選，有注入則 100% 免疫 429)
AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
CT0 = os.environ.get("TWITTER_CT0", "").strip()
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_PAT", "").strip()

# Twitter Snowflake 紀元起點 (2010-11-04 01:42:54.657 UTC)
TWITTER_EPOCH = 1288834974657

def log(message):
    """即時強制輸出日誌至控制台"""
    print(message, flush=True)

def snowflake_to_iso(tweet_id_str):
    """利用 Twitter Snowflake 演算法計算精確 UTC ISO 時間"""
    try:
        t_id = int(str(tweet_id_str).strip())
        timestamp_ms = (t_id >> 22) + TWITTER_EPOCH
        dt = datetime.utcfromtimestamp(timestamp_ms / 1000.0)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None

def load_local_tweets(filepath):
    """讀取本地既有歷史推文資料庫"""
    for path in [filepath, ALT_TWEETS_FILE]:
if os.path.exists(path):
try:
with open(path, "r", encoding="utf-8") as f:
data = json.load(f)
if isinstance(data, list) and len(data) > 0:
                        print(f"📖 成功讀取既有推文庫 ({path})：共 {len(data)} 則", flush=True)
                        log(f"📖 成功讀取本地既有資料庫 ({path})：共 {len(data)} 則")
return data
elif isinstance(data, dict):
for k in ["tweets", "data", "statuses", "results"]:
if k in data and isinstance(data[k], list):
return data[k]
return list(data.values())
except Exception as e:
                print(f"⚠️ 讀取歷史檔案失敗 ({path}): {e}", flush=True)
                log(f"⚠️ 讀取本地歷史檔案失敗 ({path}): {e}")
    return []

def fetch_yan_labs_data():
    """【軌道 1】連線 yan-labs/serenity-aleabitoreddit 遠端資料庫"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"

    log(f"🌐 [軌道 1] 正在連線 Yan Labs 遠端資料庫 (aleabitoreddit_tweets.json)...")

    for url in YAN_LABS_CANDIDATE_URLS:
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                raw_data = res.json()
                items = raw_data if isinstance(raw_data, list) else list(raw_data.values())
                
                cleaned = []
                for tw in items:
                    if not isinstance(tw, dict):
                        continue
                    t_id = str(tw.get("id") or tw.get("id_str") or tw.get("tweet_id") or "").strip()
                    if not t_id:
                        continue
                    
                    text = tw.get("text") or tw.get("full_text") or tw.get("rawContent") or ""
                    if not text and isinstance(tw.get("legacy"), dict):
                        text = tw["legacy"].get("full_text") or ""
                    if not text:
                        continue

                    created_at = tw.get("created_at") or tw.get("createdAt") or tw.get("date")
                    if not created_at or str(created_at).startswith("1970"):
                        created_at = snowflake_to_iso(t_id)

                    cleaned.append({
                        "id": t_id,
                        "id_str": t_id,
                        "text": text,
                        "created_at": created_at,
                        "favorite_count": tw.get("favorite_count") or tw.get("likes") or 0,
                        "retweet_count": tw.get("retweet_count") or tw.get("retweets") or 0,
                        "views": tw.get("views") if not isinstance(tw.get("views"), dict) else tw.get("views", {}).get("count", 0),
                        "url": tw.get("url") or f"https://twitter.com/{TARGET_HANDLE}/status/{t_id}",
                        "source": "yan_labs"
                    })

                log(f"  ✨ [軌道 1] 成功連線並自 Yan Labs 同步 {len(cleaned)} 則歷史推文！")
                return cleaned
        except Exception as e:
            log(f"  ↳ 探測異常 ({url.split('/')[-1]}): {e}")

    log("  ℹ️ Yan Labs 端點暫未回應，順暢使用本地資料庫與即時串流。")
return []

def fetch_syndication_timeline(handle):
    """通道 1：透過 Twitter 官方 Syndication Profile 抓取最新即時貼文"""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
    tweets = []
def fetch_syndication_stream(screen_name):
    """【軌道 2】官方即時串流 (支援 Cookie 憑證注入防禦 429)"""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{screen_name}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://twitter.com/{screen_name}",
    }

    # 若 GitHub Secrets 中設定了 Twitter 憑證，注入 Cookie 繞過 IP 429 限流
    if AUTH_TOKEN and CT0:
        headers["Cookie"] = f"auth_token={AUTH_TOKEN}; ct0={CT0};"
        headers["x-csrf-token"] = CT0
        log("🔑 [軌道 2] 已載入 Twitter 認證憑證 (AUTH_TOKEN / CT0)，以會員身分執行抓取...")

    fetched = []
try:
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        res = requests.get(url, headers=headers, timeout=15)
if res.status_code == 200:
            # 從回傳的 HTML / JSON 混合字串中提取 __NEXT_DATA__
match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text, re.DOTALL)
if match:
                json_data = json.loads(match.group(1))
                data = json.loads(match.group(1))
entries = (
                    json_data.get("props", {})
                    data.get("props", {})
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
                    tw_data = content.get("tweet", {})
                    if not tw_data:
                        continue

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
                    t_id = str(tw_data.get("id_str") or tw_data.get("id") or "").strip()
                    text = tw_data.get("text") or tw_data.get("full_text") or ""
                    if not t_id or not text:
                        continue

def normalize_tweet_item(raw_tweet):
    """將推文統一正規化為標準字典結構"""
    if not isinstance(raw_tweet, dict):
        return None
                    created_at = tw_data.get("created_at") or snowflake_to_iso(t_id)

    # 提取 ID
    t_id = (
        raw_tweet.get("id_str")
        or str(raw_tweet.get("id") or "")
        or str(raw_tweet.get("tweet_id") or "")
    )
    if not t_id or t_id == "0":
        return None
                    fetched.append({
                        "id": t_id,
                        "id_str": t_id,
                        "text": text,
                        "created_at": created_at,
                        "favorite_count": tw_data.get("favorite_count", 0),
                        "retweet_count": tw_data.get("retweet_count", 0),
                        "views": tw_data.get("views", {}).get("count", 0) if isinstance(tw_data.get("views"), dict) else 0,
                        "url": f"https://twitter.com/{screen_name}/status/{t_id}",
                        "source": "live_stream"
                    })
                log(f"  ✨ [軌道 2] 官方串流解析出 {len(fetched)} 則即時推文！")
        elif res.status_code == 429:
            log("  ⚠️ [軌道 2] 官方伺服器觸發 429 限流 (建議在 GitHub Secrets 加入 TWITTER_AUTH_TOKEN 與 TWITTER_CT0 解除限制)。")
        else:
            log(f"  ⚠️ [軌道 2] 回應狀態碼異常: {res.status_code}")
    except Exception as e:
        log(f"  ⚠️ [軌道 2 異常]: {e}")

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
    return fetched

    # 提取時間
    created_at = (
        raw_tweet.get("created_at")
        or raw_tweet.get("createdAt")
        or raw_tweet.get("date")
        or ""
    )
    
    # 若原始資料無標準時間，利用 Snowflake 演算法還原發布時間
    if (not created_at or created_at.startswith("1970")) and t_id.isdigit() and len(t_id) >= 10:
def enrich_recent_metrics(tweets_list, target_count=30):
    """【軌道 3】針對最新推文校準按讚、轉推與瀏覽量"""
    check_limit = min(len(tweets_list), target_count)
    log(f"🔄 [數據校準] 正在為最新 {check_limit} 則推文連線同步真實互動指標 (❤️ / 🔁 / 👁️)...")

    for tw in tweets_list[:check_limit]:
        t_id = str(tw.get("id", "")).strip()
        if not t_id:
            continue
try:
            ts_ms = (int(t_id) >> 22) + 1288834974657
            dt = datetime.utcfromtimestamp(ts_ms / 1000.0)
            created_at = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            url = f"https://cdn.syndication.twimg.com/tweet-result?id={t_id}&lang=en"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
            if res.status_code == 200 and res.text.strip().startswith("{"):
                detail = res.json()
                if "favorite_count" in detail:
                    tw["favorite_count"] = max(tw.get("favorite_count", 0), detail["favorite_count"])
                if "retweet_count" in detail:
                    tw["retweet_count"] = max(tw.get("retweet_count", 0), detail["retweet_count"])
                if "views" in detail and isinstance(detail["views"], dict):
                    tw["views"] = max(tw.get("views", 0), int(detail["views"].get("count", 0)))
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
    return tweets_list

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
def merge_and_compare_sources(local_data, yan_labs_data, live_stream_data):
    """【融合比對核心】比對本地、Yan Labs 與即時抓取資料，智慧去重與欄位優化"""
    tweets_map = {}

    total_tweets = list(existing_map.values())
    # 1. 載入本地既有資料
    for tw in local_data:
        t_id = str(tw.get("id", "")).strip()
        if t_id:
            tweets_map[t_id] = tw

    # 排序：依時間由新至舊排列
    def get_sort_key(item):
        t_id = str(item.get("id") or item.get("id_str") or "0")
        created = str(item.get("created_at") or "")
        return (created, t_id)
    yan_added = 0
    live_added = 0

    total_tweets.sort(key=get_sort_key, reverse=True)
    # 2. 比對並融合 Yan Labs 資料
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

    # 3. 比對並融合即時抓取資料 (即時資料權重最高)
    for tw in live_stream_data:
        t_id = str(tw.get("id", "")).strip()
        if not t_id:
            continue
        if t_id not in tweets_map:
            tweets_map[t_id] = tw
            live_added += 1
        else:
            tweets_map[t_id]["text"] = tw["text"]
            tweets_map[t_id]["favorite_count"] = max(tweets_map[t_id].get("favorite_count", 0), tw.get("favorite_count", 0))
            tweets_map[t_id]["retweet_count"] = max(tweets_map[t_id].get("retweet_count", 0), tw.get("retweet_count", 0))
            tweets_map[t_id]["views"] = max(tweets_map[t_id].get("views", 0), tw.get("views", 0))

    # 補齊可能缺失的時間欄位
    for t_id, tw in tweets_map.items():
        if not tw.get("created_at") or str(tw.get("created_at")).startswith("1970"):
            tw["created_at"] = snowflake_to_iso(t_id)

    merged_list = list(tweets_map.values())

    # 4. 嚴格按 Snowflake UTC 時間由新到舊排序
    merged_list.sort(
        key=lambda x: str(x.get("created_at") or snowflake_to_iso(x.get("id")) or "1970-01-01T00:00:00Z"),
        reverse=True
    )

    # 5. 針對最新推文校準真實指標
    merged_list = enrich_recent_metrics(merged_list, target_count=30)

    log(
        f"📊 [融合完成] 資料總量: {len(merged_list)} 則 "
        f"(保留本地: {len(local_data)} 則 | Yan Labs 注入: +{yan_added} 則 | 即時串流: +{live_added} 則)"
    )
    return merged_list

def save_tweets(filepath, tweets_list):
    """安全儲存至 JSON 檔案"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(tweets_list, f, ensure_ascii=False, indent=2)

def main():
    log(f"🚀 開始執行 Serenity (@{TARGET_HANDLE}) 推文抓取與資料同步流程...")
    
    local_data = load_local_tweets(TWEETS_FILE)
    yan_labs_data = fetch_yan_labs_data()
    live_stream_data = fetch_syndication_stream(TARGET_HANDLE)

    # 確保輸出目錄存在並寫入檔案
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(total_tweets, f, ensure_ascii=False, indent=2)
    final_tweets = merge_and_compare_sources(local_data, yan_labs_data, live_stream_data)

    with open(ALT_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(total_tweets, f, ensure_ascii=False, indent=2)
    save_tweets(TWEETS_FILE, final_tweets)
    save_tweets(ALT_TWEETS_FILE, final_tweets)

    print(f"🎉 推文更新完成！", flush=True)
    print(f"   • 本次新增推文數：{added_count} 則", flush=True)
    print(f"   • 資料庫總推文數：{len(total_tweets)} 則", flush=True)
    if len(total_tweets) > 0:
        latest = total_tweets[0]
        print(f"   • 最新推文發布時間：{latest.get('created_at')} (ID: {latest.get('id')})", flush=True)
        print(f"   • 最新推文摘要：{latest.get('text', '')[:60]}...", flush=True)
    if final_tweets:
        latest = final_tweets[0]
        log(f"🎉 推文資料庫更新完畢！最新貼文時間: {latest.get('created_at')} (ID: {latest.get('id')})")
        log(f"   摘要: {latest.get('text', '')[:70]}...")

if __name__ == "__main__":
main()
