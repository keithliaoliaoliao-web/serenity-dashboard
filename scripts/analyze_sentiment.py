"""用 Gemini 分析每則推文：整體立場、「每一檔股票各自的立場」、重點摘要、繁中翻譯、風險提示。

改進重點：
  • 同一則推文提到多檔股票時，每檔各有自己的立場（看多 A、看空 B 不會再混在一起）
  • 強制 Gemini 回傳固定 JSON 格式；格式不對就不存，下次重試（不再把亂碼存進快取）
  • 舊快取中「提到 2 檔以上股票」的推文會在新推文處理完後自動重新分析
"""
import os
import time
from datetime import datetime, timezone

from common import (log, extract_tickers, snowflake_to_dt, tweet_id_of, tweet_text_of,
                    load_tweet_list, load_sentiment_cache, save_json, normalize_sentiment)
from gemini_client import GeminiClient

TWEETS_FILE = "data/tweets.json"
CACHE_FILE = "data/sentiment_cache.json"
TOTAL_TARGET = int(os.environ.get("TOTAL_TARGET") or 50)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
ANALYZE_MACRO_TWEETS = True       # 沒有 $代號 的大盤／總經推文也分析

SENT = {"type": "STRING", "enum": ["Bullish", "Bearish", "Neutral"]}
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "overall": SENT,
        "stances": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"ticker": {"type": "STRING"}, "sentiment": SENT},
            "required": ["ticker", "sentiment"]}},
        "summary": {"type": "STRING"},
        "translation_zh": {"type": "STRING"},
        "risk": {"type": "STRING"},
    },
    "required": ["overall", "stances", "summary", "translation_zh", "risk"],
}


def build_prompt(text, tickers):
    return f"""你是專業的美股社群量化分析師。請只根據下面這則推文判斷，不要加入推文以外的資訊。

已偵測到的股票代號：{', '.join('$' + t for t in tickers) if tickers else '無（大盤或總經貼文）'}
推文內容：
{text}

請回傳 JSON，規則如下：
1. stances：對每一個已偵測到的代號各給一個立場。Bullish＝看多，Bearish＝看空，Neutral＝中立或只是提及。同一則推文對不同股票可以有不同立場。沒有代號就回傳空陣列。
2. overall：整則推文的整體立場。
3. summary：繁體中文 25 字內的觀點重點，需點出標的與立場。
4. translation_zh：符合台灣財經用語的流暢繁體中文翻譯。
5. risk：若推文提到風險、疑慮或警告（例如估值過高、股權稀釋、競爭、需求放緩），用繁體中文 40 字內寫下；沒有就回傳空字串。"""


def validate(data, tickers):
    """檢查並整理 Gemini 的回覆；不合格回傳 None。"""
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary") or "").strip()
    translation = str(data.get("translation_zh") or "").strip()
    if not summary or not translation:
        return None
    overall = normalize_sentiment(data.get("overall"))
    found = {}
    for item in data.get("stances") or []:
        if isinstance(item, dict) and item.get("ticker"):
            sym = str(item["ticker"]).upper().lstrip("$").strip()
            found[sym] = normalize_sentiment(item.get("sentiment"))
    stances = {}
    for tk in tickers:
        stances[tk] = found.get(tk) or (overall if len(tickers) == 1 else "Neutral")
    return {"overall": overall, "stances": stances, "summary": summary,
            "translation_zh": translation, "risk": str(data.get("risk") or "").strip()}


def main():
    log("🚀 開始 Serenity 推文 AI 分析...")
    if not GEMINI_API_KEY:
        log("❌ 沒有偵測到 GEMINI_API_KEY（請到 GitHub Secrets 設定），略過本步驟")
        return

    tweets = load_tweet_list(TWEETS_FILE)
    cache = load_sentiment_cache(CACHE_FILE)
    log(f"📊 推文 {len(tweets)} 則｜已分析 {len(cache)} 則")

    new_items, legacy_items = [], []
    for t in tweets:
        if not isinstance(t, dict):
            continue
        t_id, text = tweet_id_of(t), tweet_text_of(t)
        if not t_id or not text:
            continue
        tickers = extract_tickers(text)
        if t_id not in cache:
            if tickers or ANALYZE_MACRO_TWEETS:
                new_items.append((t_id, text, tickers))
        elif "stances" not in cache[t_id] and len(tickers) >= 2 and not cache[t_id].get("status"):
            legacy_items.append((t_id, text, tickers))   # 舊版把多檔股票套同一個立場，需要重做

    def newest_first(item):
        dt = snowflake_to_dt(item[0])
        return dt.timestamp() if dt else 0

    new_items.sort(key=newest_first, reverse=True)
    legacy_items.sort(key=newest_first, reverse=True)
    pending = new_items + legacy_items
    log(f"🔍 待分析：新推文 {len(new_items)} 則 + 需重做的舊推文 {len(legacy_items)} 則（本次上限 {TOTAL_TARGET}）")
    if not pending:
        log("✅ 沒有需要分析的推文")
        return

    client = GeminiClient(GEMINI_API_KEY)
    batch = pending[:TOTAL_TARGET]
    ok_count, fail_streak = 0, 0

    for idx, (t_id, text, tickers) in enumerate(batch, 1):
        label = ", ".join("$" + t for t in tickers) or "大盤/總經"
        status, payload, model = client.generate_json(build_prompt(text, tickers), SCHEMA)

        if status == "ok":
            result = validate(payload, tickers)
            if result is None:
                status, payload = "error", "回覆內容不完整"
        if status == "ok":
            fail_streak = 0
            cache[t_id] = {
                "id": t_id, "tweet_id": t_id,
                "sentiment": result["overall"], "stances": result["stances"],
                "summary": result["summary"], "translation_zh": result["translation_zh"],
                "risk": result["risk"], "model": model,
                "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            ok_count += 1
            log(f"  [{idx}/{len(batch)}] ✅ {t_id} ({label}) → {result['overall']} {result['summary']}")
            if ok_count % 5 == 0:
                save_json(CACHE_FILE, cache, indent=2)
        elif status == "blocked":
            fail_streak = 0
            log(f"  [{idx}/{len(batch)}] 🚫 {t_id} 被安全審查擋下（{payload}），標記為略過")
            if t_id not in cache:
                cache[t_id] = {"id": t_id, "tweet_id": t_id, "sentiment": "Neutral",
                               "stances": {tk: "Neutral" for tk in tickers},
                               "summary": "", "translation_zh": "", "risk": "", "status": "blocked"}
        else:
            fail_streak += 1
            log(f"  [{idx}/{len(batch)}] ⚠️ {t_id} 分析失敗（下次重試）：{payload}")
            if fail_streak >= 5:
                log("⛔ 連續 5 則失敗，可能是額度用完或金鑰有問題，提前結束本次分析")
                break
        time.sleep(1.0)

    save_json(CACHE_FILE, cache, indent=2)
    log(f"🎉 本次成功 {ok_count} 則｜累計 {len(cache)} / {len(tweets)} ({round(len(cache) / max(len(tweets), 1) * 100, 1)}%)")


if __name__ == "__main__":
    main()
