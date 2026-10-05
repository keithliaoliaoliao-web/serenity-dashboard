"""為每檔股票用 Gemini 整理「投資論點演變」，存進 data/thesis_cache.json，網頁直接讀取。

設計重點：
  • AI 只負責「選哪幾則貼文」和「寫說明」；貼文連結與日期由網頁用貼文 ID 自己查，
    所以每個結論的來源一定是真的，AI 編不出假連結。
  • 只有「該股票有新推文、或有更多推文完成分析」才會重新整理，節省免費額度。
  • 每次最多整理 THESIS_MAX_PER_RUN 檔（預設 15），舊的積壓會在幾天內慢慢補完。
  • 只有 2 則以上推文的股票才用 AI；只提到 1 次的股票由網頁自動彙整即可。
"""
import os
import time
from datetime import datetime, timezone

from common import (log, extract_tickers, snowflake_to_dt, tweet_id_of, tweet_text_of,
                    load_tweet_list, load_sentiment_cache, load_json, save_json, stance_for)
from gemini_client import GeminiClient

TWEETS_FILE = "data/tweets.json"
CACHE_FILE = "data/sentiment_cache.json"
THESIS_FILE = "data/thesis_cache.json"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MAX_PER_RUN = int(os.environ.get("THESIS_MAX_PER_RUN") or 15)
MIN_TWEETS = 2
MAX_TWEETS_IN_PROMPT = 60

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "thesis_story": {"type": "STRING"},
        "milestones": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"tweet_id": {"type": "STRING"}, "title": {"type": "STRING"},
                           "significance": {"type": "STRING"}},
            "required": ["tweet_id", "title", "significance"]}},
        "risks": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"tweet_id": {"type": "STRING"}, "point": {"type": "STRING"}},
            "required": ["tweet_id", "point"]}},
    },
    "required": ["thesis_story", "milestones", "risks"],
}


def collect_by_ticker(tweets, cache):
    by_ticker = {}
    for t in tweets:
        if not isinstance(t, dict):
            continue
        t_id, text = tweet_id_of(t), tweet_text_of(t)
        dt = snowflake_to_dt(t_id)
        if not t_id or not text or not dt:
            continue
        entry = cache.get(t_id)
        for tk in extract_tickers(text):
            by_ticker.setdefault(tk, []).append({
                "id": t_id, "ts": dt.timestamp(), "date": dt.strftime("%Y-%m-%d"),
                "text": " ".join(text.split()),
                "likes": int(t.get("favorite_count") or 0), "views": int(t.get("views") or 0),
                "stance": stance_for(entry, tk),
                "analyzed": bool(entry and entry.get("summary")),
            })
    for items in by_ticker.values():
        items.sort(key=lambda x: x["ts"])
    return by_ticker


def pick_for_prompt(items):
    if len(items) <= MAX_TWEETS_IN_PROMPT:
        return items
    chosen = {x["id"]: x for x in items[:3]}
    top = sorted(items, key=lambda x: x["likes"] * 5 + x["views"], reverse=True)[:20]
    chosen.update({x["id"]: x for x in top})
    for x in items[-37:]:
        chosen[x["id"]] = x
    return sorted(chosen.values(), key=lambda x: x["ts"])[-MAX_TWEETS_IN_PROMPT:]


def build_prompt(ticker, shown):
    lines = "\n".join(f"[{x['id']}] {x['date']} | {x['stance']} | {x['text'][:450]}" for x in shown)
    return f"""你是專業的美股投資研究助理。以下是推特用戶 Serenity (@aleabitoreddit) 歷來提到 {ticker} 的貼文，由舊到新排列，每行格式為「[貼文ID] 日期 | 立場 | 內容」。
請「只根據這些貼文」整理他對 {ticker} 的投資論點，不要加入貼文以外的資訊，也不要自己預測股價。

{lines}

請回傳 JSON：
- thesis_story：繁體中文 150～300 字，依時間說明這個論點如何形成、有哪些轉折或加碼理由、目前立場。提到事件時帶上年月（例如「2025 年 3 月」）。
- milestones：最多 3 則，挑出最能代表論點走向的貼文，依時間由舊到新。tweet_id 必須是上面列出的貼文 ID；title 12 字內；significance 60 字內，說明這則貼文為什麼改變或定義了論點。
- risks：Serenity 曾指出的風險或疑慮，最多 4 則。tweet_id 必須來自上面貼文；point 40 字內。沒有就回傳空陣列。"""


def validate(data, shown_ids):
    if not isinstance(data, dict):
        return None
    story = str(data.get("thesis_story") or "").strip()
    milestones = [{"tweet_id": str(m.get("tweet_id")), "title": str(m.get("title") or "").strip(),
                   "significance": str(m.get("significance") or "").strip()}
                  for m in (data.get("milestones") or [])
                  if isinstance(m, dict) and str(m.get("tweet_id")) in shown_ids][:3]
    risks = [{"tweet_id": str(r.get("tweet_id")), "point": str(r.get("point") or "").strip()}
             for r in (data.get("risks") or [])
             if isinstance(r, dict) and str(r.get("tweet_id")) in shown_ids and r.get("point")][:4]
    if len(story) < 30 or not milestones:
        return None
    return {"thesis_story": story, "milestones": milestones, "risks": risks}


def main():
    log("🧠 開始整理個股投資論點...")
    if not GEMINI_API_KEY:
        log("❌ 沒有偵測到 GEMINI_API_KEY，略過本步驟（網頁會改用自動彙整版）")
        return

    tweets = load_tweet_list(TWEETS_FILE)
    cache = load_sentiment_cache(CACHE_FILE)
    thesis_db = load_json(THESIS_FILE, {})
    if not isinstance(thesis_db, dict):
        thesis_db = {}

    by_ticker = collect_by_ticker(tweets, cache)
    stale, never = [], []
    for tk, items in by_ticker.items():
        if len(items) < MIN_TWEETS:
            continue
        sig = (len(items), items[-1]["id"], sum(1 for x in items if x["analyzed"]))
        old = thesis_db.get(tk)
        if old is None:
            never.append((len(items), tk))
        elif (old.get("tweet_count"), old.get("last_tweet_id"), old.get("analyzed_count")) != sig:
            stale.append((items[-1]["ts"], tk))
    stale.sort(reverse=True)       # 有新推文的股票優先，越新越先
    never.sort(reverse=True)       # 還沒整理過的，提及越多越先
    queue = [tk for _, tk in stale] + [tk for _, tk in never]
    log(f"🔍 需要更新 {len(stale)} 檔｜尚未整理 {len(never)} 檔｜本次上限 {MAX_PER_RUN}")
    if not queue:
        log("✅ 論點都是最新的")
        return

    client = GeminiClient(GEMINI_API_KEY)
    done, fail_streak = 0, 0
    for tk in queue[:MAX_PER_RUN]:
        items = by_ticker[tk]
        shown = pick_for_prompt(items)
        status, payload, model = client.generate_json(build_prompt(tk, shown), SCHEMA, temperature=0.3)
        result = validate(payload, {x["id"] for x in shown}) if status == "ok" else None
        if result:
            fail_streak = 0
            thesis_db[tk] = {
                "ticker": tk, "ai": True, **result,
                "tweet_count": len(items), "last_tweet_id": items[-1]["id"],
                "analyzed_count": sum(1 for x in items if x["analyzed"]),
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "model": model,
            }
            done += 1
            log(f"  ✅ ${tk}（{len(items)} 則推文）via {model}")
            save_json(THESIS_FILE, thesis_db, indent=2)
        else:
            fail_streak += 1
            log(f"  ⚠️ ${tk} 失敗（下次重試）：{payload if status != 'ok' else '回覆內容不完整'}")
            if fail_streak >= 3:
                log("⛔ 連續 3 檔失敗，提前結束")
                break
        time.sleep(2.0)

    save_json(THESIS_FILE, thesis_db, indent=2)
    log(f"🎉 本次更新 {done} 檔，論點庫共 {len(thesis_db)} 檔")


if __name__ == "__main__":
    main()
