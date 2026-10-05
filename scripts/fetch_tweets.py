"""抓取 Serenity (@aleabitoreddit) 推文並與本地資料庫合併。

三條來源：
  軌道 1  yan-labs 遠端歷史資料庫
  軌道 2  Twitter 官方即時串流（可選用登入憑證）
  軌道 3  針對最新推文校準按讚／轉推／瀏覽數（並補回被截短的長文）

每次執行都會把「這次抓取是否成功」寫進 data/status.json，
網頁頂端會顯示，資料過期時一眼就看得出來。
"""
import os
import re
import json
import time
from datetime import datetime, timezone

import requests

from common import (TARGET_HANDLE, log, snowflake_to_iso, tweet_id_of, tweet_text_of,
                    load_tweet_list, save_json)

TWEETS_FILE = "data/tweets.json"
ALT_TWEETS_FILE = "data/aleabitoreddit_tweets.json"   # 舊版備份檔，只在主檔不存在時讀取
STATUS_FILE = "data/status.json"

YAN_LABS_CANDIDATE_URLS = [
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json",
    "https://cdn.jsdelivr.net/gh/yan-labs/serenity-aleabitoreddit@main/data/aleabitoreddit_tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/master/data/aleabitoreddit_tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/tweets.json",
]

AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
CT0 = os.environ.get("TWITTER_CT0", "").strip()
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_PAT", "").strip()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def safe_int(val):
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    return int(s) if s.isdigit() else 0


def metric(tw, *keys):
    legacy = tw.get("legacy") if isinstance(tw.get("legacy"), dict) else {}
    for k in keys:
        for src in (tw, legacy):
            v = safe_int(src.get(k))
            if v:
                return v
    return 0


def views_of(tw):
    v = tw.get("views")
    if isinstance(v, dict):
        v = v.get("count")
    return safe_int(v) or safe_int(tw.get("view_count")) or safe_int(tw.get("viewCount"))


def normalize_item(tw, source):
    if not isinstance(tw, dict):
        return None
    t_id = tweet_id_of(tw)
    text = tweet_text_of(tw)
    if not t_id or not text:
        return None
    return {
        "id": t_id,
        "id_str": t_id,
        "text": text,
        # 時間一律由推文 ID 推算，避免不同來源格式不同造成排序錯亂
        "created_at": snowflake_to_iso(t_id) or str(tw.get("created_at") or tw.get("createdAt") or ""),
        "favorite_count": metric(tw, "favorite_count", "likes", "like_count"),
        "retweet_count": metric(tw, "retweet_count", "retweets"),
        "views": views_of(tw),
        "url": tw.get("url") or f"https://twitter.com/{TARGET_HANDLE}/status/{t_id}",
        "source": source,
    }


def load_local_tweets():
    for path in (TWEETS_FILE, ALT_TWEETS_FILE):
        data = load_tweet_list(path)
        if data:
            log(f"📖 讀取本地資料庫 ({path})：{len(data)} 則")
            return data
    return []


def fetch_yan_labs_data():
    """軌道 1。回傳 (推文清單, 是否成功)。"""
    headers = {"User-Agent": UA}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    log("🌐 [軌道 1] 連線 Yan Labs 遠端資料庫...")
    for url in YAN_LABS_CANDIDATE_URLS:
        try:
            res = requests.get(url, headers=headers, timeout=30)
            if res.status_code == 200 and res.text.strip().startswith(("[", "{")):
                raw = res.json()
                items = raw if isinstance(raw, list) else list(raw.values())
                cleaned = [n for n in (normalize_item(tw, "yan_labs") for tw in items) if n]
                log(f"  ✨ [軌道 1] 同步 {len(cleaned)} 則")
                return cleaned, True
            log(f"  ↳ {url.split('/')[-1]} 回應 HTTP {res.status_code}")
        except Exception as e:
            log(f"  ↳ 探測異常 ({url.split('/')[-1]}): {e}")
    log("  ⚠️ [軌道 1] 所有端點都失敗")
    return [], False


def fetch_syndication_stream(screen_name):
    """軌道 2。回傳 (推文清單, 是否成功)。"""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{screen_name}"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://twitter.com/{screen_name}",
    }
    if AUTH_TOKEN and CT0:
        headers["Cookie"] = f"auth_token={AUTH_TOKEN}; ct0={CT0};"
        headers["x-csrf-token"] = CT0
        log("🔑 [軌道 2] 已載入 Twitter 登入憑證")

    fetched = []
    try:
        res = requests.get(url, headers=headers, timeout=20)
        if res.status_code != 200:
            log(f"  ⚠️ [軌道 2] HTTP {res.status_code}" + ("（被限流）" if res.status_code == 429 else ""))
            return [], False
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text, re.DOTALL)
        if not match:
            log("  ⚠️ [軌道 2] 頁面格式改變，找不到資料")
            return [], False
        entries = (json.loads(match.group(1)).get("props", {}).get("pageProps", {})
                   .get("timeline", {}).get("entries", []))
        for entry in entries:
            tw = (entry.get("content") or {}).get("tweet") or {}
            owner = str((tw.get("user") or {}).get("screen_name") or "").lower()
            if owner and owner != screen_name.lower():
                continue   # 排除轉推別人的內容
            n = normalize_item(tw, "live_stream")
            if n:
                fetched.append(n)
        log(f"  ✨ [軌道 2] 解析出 {len(fetched)} 則即時推文")
        return fetched, len(fetched) > 0
    except Exception as e:
        log(f"  ⚠️ [軌道 2 異常]: {e}")
        return [], False


def enrich_recent_metrics(tweets, target_count=30):
    """軌道 3：校準最新推文的互動數，並補回被截短的長文。"""
    check = min(len(tweets), target_count)
    log(f"🔄 [軌道 3] 校準最新 {check} 則推文的互動指標...")
    for tw in tweets[:check]:
        try:
            res = requests.get(f"https://cdn.syndication.twimg.com/tweet-result?id={tw['id']}&lang=en",
                               headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            if res.status_code == 200 and res.text.strip().startswith("{"):
                d = res.json()
                tw["favorite_count"] = max(safe_int(tw.get("favorite_count")), safe_int(d.get("favorite_count")))
                tw["retweet_count"] = max(safe_int(tw.get("retweet_count")), safe_int(d.get("retweet_count")))
                tw["views"] = max(safe_int(tw.get("views")), views_of(d))
                if len(str(d.get("text") or "")) > len(tw.get("text", "")):
                    tw["text"] = d["text"]
        except Exception:
            pass
        time.sleep(0.15)
    return tweets


def merge_sources(local, yan, live):
    """去重合併。文字永遠保留「比較長的版本」（即時串流常常是截短的）；
    按讚等數字取最大值。"""
    tweets = {}
    for tw in local:
        t_id = tweet_id_of(tw) if isinstance(tw, dict) else ""
        if t_id:
            tw["id"] = t_id
            tweets[t_id] = tw

    added = {"yan": 0, "live": 0}

    def absorb(items, label):
        for tw in items:
            t_id = tw["id"]
            cur = tweets.get(t_id)
            if cur is None:
                tweets[t_id] = tw
                added[label] += 1
                continue
            if len(tw.get("text", "")) > len(cur.get("text", "")):
                cur["text"] = tw["text"]
            for k in ("favorite_count", "retweet_count", "views"):
                cur[k] = max(safe_int(cur.get(k)), safe_int(tw.get(k)))

    absorb(yan, "yan")
    absorb(live, "live")

    for t_id, tw in tweets.items():
        iso = snowflake_to_iso(t_id)
        if iso:
            tw["created_at"] = iso

    merged = sorted(tweets.values(), key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else 0, reverse=True)
    merged = enrich_recent_metrics(merged, 30)
    log(f"📊 [融合完成] 共 {len(merged)} 則（本地 {len(local)}｜Yan Labs 新增 {added['yan']}｜即時串流新增 {added['live']}）")
    return merged, added["yan"] + added["live"]


def main():
    log(f"🚀 開始抓取 Serenity (@{TARGET_HANDLE}) 推文...")
    local = load_local_tweets()
    yan, yan_ok = fetch_yan_labs_data()
    live, live_ok = fetch_syndication_stream(TARGET_HANDLE)

    if not yan_ok and not live_ok:
        log("❌ 所有推文來源都失敗，本次沿用舊資料（網頁上會顯示警告）")

    final, new_count = merge_sources(local, yan, live)
    save_json(TWEETS_FILE, final)

    save_json(STATUS_FILE, {
        "last_run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "yan_labs_ok": yan_ok,
        "live_stream_ok": live_ok,
        "tweet_count": len(final),
        "new_tweets_this_run": new_count,
        "latest_tweet_at": final[0]["created_at"] if final else None,
    }, indent=2)

    if final:
        log(f"🎉 完成。最新貼文：{final[0]['created_at']}（ID {final[0]['id']}）")


if __name__ == "__main__":
    main()
