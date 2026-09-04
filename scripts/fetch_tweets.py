import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests

# ==========================================
# 參數設定區 (Serenity Tracker: aleabitoreddit)
# ==========================================
TARGET_HANDLE = "aleabitoreddit"
OUTPUT_FILE = "data/tweets.json"
ALT_OUTPUT_FILE = "data/aleabitoreddit_tweets.json"

# 多節點公開 Twitter 鏡像解析池 (繞過 GitHub Actions 429 IP 限制)
MIRROR_ENDPOINTS = [
    f"https://rsshub.app/twitter/user/{TARGET_HANDLE}",
    f"https://rsshub.rssforever.com/twitter/user/{TARGET_HANDLE}",
    f"https://nitter.privacydev.net/{TARGET_HANDLE}/rss",
    f"https://nitter.poast.org/{TARGET_HANDLE}/rss",
    f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{TARGET_HANDLE}"
]

TWITTER_EPOCH = 1288834974657

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
}

def log(msg):
    print(msg, flush=True)

def snowflake_to_iso(tweet_id_str):
    try:
        t_id = int(str(tweet_id_str).strip())
        timestamp_ms = (t_id >> 22) + TWITTER_EPOCH
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None

def load_local_tweets():
    for path in [OUTPUT_FILE, ALT_OUTPUT_FILE]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        log(f"📖 成功讀取本地既有推文庫 ({path})：共 {len(data)} 則")
                        return data
            except Exception as e:
                log(f"⚠️ 讀取本地歷史檔案失敗 ({path}): {e}")
    return []

def clean_html_tags(raw_html):
    if not raw_html:
        return ""
    clean = re.sub(r"<a\s+[^>]*href=[\"'](https?://[^\s\"']+)[\"'][^>]*>.*?</a>", r" \1 ", raw_html)
    clean = re.sub(r"<br\s*/?>", "\n", clean)
    clean = re.sub(r"<[^>]+>", "", clean)
    return clean.strip()

def parse_rss_feed(xml_text):
    """解析 RSS/XML 格式的推文鏡像"""
    tweets = []
    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return []

        for item in channel.findall("item"):
            link = item.findtext("link") or ""
            desc = item.findtext("description") or ""
            pub_date = item.findtext("pubDate") or ""

            # 擷取推文 ID
            id_match = re.search(r"status/(\d+)", link)
            if not id_match:
                continue
            t_id = id_match.group(1).strip()

            # 解析文字內容
            text = clean_html_tags(desc)
            if not text:
                continue

            # 轉換時間格式為 ISO
            iso_date = ""
            if pub_date:
                try:
                    dt = datetime.strptime(pub_date[:25], "%a, %d %b %Y %H:%M:%S")
                    iso_date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    iso_date = snowflake_to_iso(t_id)
            else:
                iso_date = snowflake_to_iso(t_id)

            tweets.append({
                "id": t_id,
                "id_str": t_id,
                "text": text,
                "created_at": iso_date,
                "favorite_count": 0,
                "retweet_count": 0,
                "views": 0,
                "url": f"https://twitter.com/{TARGET_HANDLE}/status/{t_id}"
            })
    except Exception as e:
        log(f"  ↳ XML 解析異常: {e}")
    return tweets

def parse_syndication_html(html_text):
    """解析 Twitter Syndication HTML 結構"""
    tweets = []
    try:
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            entries = (
                data.get("props", {})
                .get("pageProps", {})
                .get("timeline", {})
                .get("entries", [])
            )
            for entry in entries:
                tw_data = entry.get("content", {}).get("tweet", {})
                if not tw_data:
                    continue
                t_id = str(tw_data.get("id_str") or tw_data.get("id") or "").strip()
                text = tw_data.get("text") or tw_data.get("full_text") or ""
                if not t_id or not text:
                    continue

                created_at = tw_data.get("created_at") or snowflake_to_iso(t_id)

                tweets.append({
                    "id": t_id,
                    "id_str": t_id,
                    "text": text,
                    "created_at": created_at,
                    "favorite_count": tw_data.get("favorite_count", 0),
                    "retweet_count": tw_data.get("retweet_count", 0),
                    "views": tw_data.get("views", {}).get("count", 0) if isinstance(tw_data.get("views"), dict) else 0,
                    "url": f"https://twitter.com/{TARGET_HANDLE}/status/{t_id}"
                })
    except Exception as e:
        log(f"  ↳ Syndication 解析異常: {e}")
    return tweets

def fetch_from_mirrors():
    """輪詢鏡像池獲取最新推文"""
    for idx, url in enumerate(MIRROR_ENDPOINTS, 1):
        log(f"🌐 正在嘗試節點 {idx}/{len(MIRROR_ENDPOINTS)}: {url.split('/')[2]}...")
        try:
            res = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
            if res.status_code == 200 and res.text:
                if "<rss" in res.text or "<feed" in res.text:
                    items = parse_rss_feed(res.text)
                else:
                    items = parse_syndication_html(res.text)

                if items and len(items) > 0:
                    log(f"  ✨ 節點 {idx} 連線成功！解析出 {len(items)} 則近期推文")
                    return items
            else:
                log(f"  ↳ 節點回應狀態碼: {res.status_code}")
        except Exception as e:
            log(f"  ↳ 節點探測逾時或異常: {e}")
        time.sleep(1)

    log("⚠️ 所有公開鏡像節點暫時無法連線。")
    return []

def main():
    log(f"🚀 開始執行 Serenity (@{TARGET_HANDLE}) 自主推文抓取流程...")

    existing_tweets = load_local_tweets()
    existing_map = {}
    for item in existing_tweets:
        if isinstance(item, dict):
            t_id = str(item.get("id") or item.get("id_str") or "").strip()
            if t_id:
                existing_map[t_id] = item

    new_tweets = fetch_from_mirrors()

    added_count = 0
    for tw in new_tweets:
        t_id = tw["id"]
        if t_id not in existing_map:
            existing_map[t_id] = tw
            added_count += 1
        else:
            if len(tw["text"]) > len(existing_map[t_id].get("text", "")):
                existing_map[t_id]["text"] = tw["text"]
            existing_map[t_id]["favorite_count"] = max(existing_map[t_id].get("favorite_count", 0), tw.get("favorite_count", 0))
            existing_map[t_id]["retweet_count"] = max(existing_map[t_id].get("retweet_count", 0), tw.get("retweet_count", 0))

    final_tweets = list(existing_map.values())

    # 嚴格按 Snowflake UTC 時間降序排列
    final_tweets.sort(
        key=lambda x: str(x.get("created_at") or snowflake_to_iso(x.get("id")) or "1970-01-01T00:00:00Z"),
        reverse=True
    )

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_tweets, f, ensure_ascii=False, indent=2)

    with open(ALT_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_tweets, f, ensure_ascii=False, indent=2)

    log(f"🎉 推文資料庫同步完成！")
    log(f"   • 本次新增推文：{added_count} 則")
    log(f"   • 資料庫總推文：{len(final_tweets)} 則")
    if final_tweets:
        latest = final_tweets[0]
        log(f"   • 最新推文發布時間：{latest.get('created_at')} (ID: {latest.get('id')})")
        log(f"   • 最新推文摘要：{latest.get('text', '')[:70]}...")

if __name__ == "__main__":
    main()
