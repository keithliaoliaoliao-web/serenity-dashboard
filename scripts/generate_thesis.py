import json
import os
import re
import time
from datetime import datetime
import requests

# ==========================================
# 參數設定
# ==========================================
TWEETS_FILE = "data/tweets.json"
SENTIMENT_CACHE = "data/sentiment_cache.json"
OUTPUT_THESIS_FILE = "data/thesis_cache.json"

# 可於環境變數中設定 GEMINI_API_KEY (可選)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

TWITTER_EPOCH = 1288834974657

def snowflake_to_iso(tweet_id_str):
    try:
        t_id = int(str(tweet_id_str).strip())
        timestamp_ms = (t_id >> 22) + TWITTER_EPOCH
        dt = datetime.utcfromtimestamp(timestamp_ms / 1000.0)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "未知時間"

def load_json(filepath, default_val):
    if not os.path.exists(filepath):
        return default_val
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_val

def extract_tickers(text):
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Za-z]{1,6})\b", text)
    blacklist = {
        "USD", "USDT", "BTC", "ETH", "CAD", "EUR", "ATH", "CEO", "CFO", "CTO",
        "AI", "FOMC", "FED", "CPI", "PPI", "GDP", "DD", "EOD", "YOLO", "NEW",
        "BUY", "SELL", "HOLD", "CALL", "PUT", "AND", "THE", "TECH", "EV"
    }
    return sorted(list(set(t.upper() for t in matches if t.upper() not in blacklist and t.isalpha())))

def call_gemini_for_thesis(ticker, tweets):
    """使用 Google Gemini API 深度提煉個股投資故事與關鍵里程碑"""
    if not GEMINI_API_KEY:
        return None

    # 挑選具代表性的推文上下文（最多 25 則）
    sample_tweets = tweets[:25]
    tweet_contexts = []
    for idx, t in enumerate(sample_tweets):
        tweet_contexts.append(f"[{t.get('date')}] (立場: {t.get('sentiment')}) {t.get('summary') or t.get('text')[:120]}")

    prompt = f"""
你是一位專業的美股基本面與社群觀點分析師。請根據以下關於股票 ${ticker} 的歷史貼文紀錄，提煉出結構化的投資論點演變分析。

【歷史推文紀錄】：
{chr(10).join(tweet_contexts)}

請輸出繁體中文，並嚴格依照以下 JSON 格式回傳（不要包含任何 markdown 標籤或額外文字）：
{{
  "thesis_story": "用 150-200 字總結 ${ticker} 的投資故事演進，說明最初為何被看好、過程中論點如何變化、目前的定調是什麼。",
  "milestones": [
    {{
      "title": "里程碑標題（例如：首次建倉與初始論點）",
      "date": "對應日期",
      "summary": "該階段的核心觀點摘要",
      "significance": "為什麼這篇觀點對整個投資論點至關重要"
    }}
  ],
  "risks": [
    {{
      "date": "對應日期",
      "point": "曾提及的風險或疑慮警語"
    }}
  ]
}}
注意：milestones 最多 3 個，risks 最多 3 個。
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code == 200:
            res_json = res.json()
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(raw_text)
            
            # 關聯原始推文連結
            milestones = []
            for m in parsed.get("milestones", []):
                matched_tweet = next((t for t in tweets if t.get("date") == m.get("date")), tweets[0])
                milestones.append({
                    "title": m.get("title", "核心觀點里程碑"),
                    "date": m.get("date", matched_tweet.get("date")),
                    "summary": m.get("summary", matched_tweet.get("summary") or matched_tweet.get("text")[:60]),
                    "significance": m.get("significance", "定義了個股論點走向的重要貼文。"),
                    "url": matched_tweet.get("url", "#"),
                    "sentiment": matched_tweet.get("sentiment", "Neutral")
                })
            
            risks = []
            for r in parsed.get("risks", []):
                matched_tweet = next((t for t in tweets if t.get("date") == r.get("date")), tweets[0])
                risks.append({
                    "date": r.get("date", matched_tweet.get("date")),
                    "point": r.get("point", "歷史風險警戒提示"),
                    "url": matched_tweet.get("url", "#")
                })

            sorted_tweets = sorted(tweets, key=lambda x: str(x.get("date", "")), reverse=False)
            bull_count = sum(1 for t in tweets if t.get("sentiment") == "Bullish")
            total = len(tweets)

            return {
                "ticker": ticker,
                "thesis_story": parsed.get("thesis_story", ""),
                "first_date": sorted_tweets[0].get("date", "-"),
                "latest_stance": sorted_tweets[-1].get("sentiment", "Neutral"),
                "total_mentions": total,
                "bull_ratio": round((bull_count / total) * 100) if total else 0,
                "milestones": milestones[:3],
                "risks": risks[:3]
            }
    except Exception as e:
        print(f"  ⚠️ Gemini API 呼叫略過 (${ticker}): {e}", flush=True)

    return None

def build_heuristic_thesis(ticker, tweets):
    """啟發式規則引擎（當無 API Key 時的備用方案）"""
    sorted_tweets = sorted(tweets, key=lambda x: str(x.get("date", "")), reverse=False)
    if not sorted_tweets:
        return None

    first = sorted_tweets[0]
    latest = sorted_tweets[-1]
    
    bull_count = sum(1 for t in tweets if t.get("sentiment") == "Bullish")
    total = len(tweets)
    bull_pct = round((bull_count / total) * 100) if total else 0

    thesis_story = (
        f"${ticker} 首次於 {first.get('date', '早期')} 受到關注。"
        f"在過去的追蹤歷程中，共累積 {total} 則深度討論，整體社群立場偏向 "
        f"{'看多 (Bullish)' if bull_pct >= 60 else ('震盪/中立' if bull_pct >= 40 else '防守/看空')}（多方佔比 {bull_pct}%）。"
    )
    if latest.get("summary"):
        thesis_story += f" 最新一次觀點指出：{latest.get('summary')}"

    milestones = []
    # 里程碑 1: 首次提及
    milestones.append({
        "date": first.get("date", "-"),
        "title": "首次關注建案與初始投資論點",
        "summary": first.get("summary") or first.get("text", "")[:80] + "...",
        "significance": f"定義了 ${ticker} 最初被納入追蹤清單的核心驅動因素與估值基準。",
        "url": first.get("url", "#"),
        "sentiment": first.get("sentiment", "Neutral")
    })

    # 里程碑 2: 高熱度貼文
    ranked_by_impact = sorted(tweets, key=lambda x: (x.get("likes", 0) * 5 + x.get("views", 0)), reverse=True)
    high_impact = next((t for t in ranked_by_impact if t.get("id") != first.get("id")), None)
    if high_impact:
        milestones.append({
            "date": high_impact.get("date", "-"),
            "title": "重大催化劑與市場共識發酵",
            "summary": high_impact.get("summary") or high_impact.get("text", "")[:80] + "...",
            "significance": "社群高度共鳴的關鍵貼文，確立了該標的在產業週期或財報催化劑中的爆發潛力。",
            "url": high_impact.get("url", "#"),
            "sentiment": high_impact.get("sentiment", "Neutral")
        })

    # 里程碑 3: 最新定調
    if latest.get("id") != first.get("id") and (not high_impact or latest.get("id") != high_impact.get("id")):
        milestones.append({
            "date": latest.get("date", "-"),
            "title": "近期最新立場與格局更新",
            "summary": latest.get("summary") or latest.get("text", "")[:80] + "...",
            "significance": "代表當前最新定調，作為短中期持股與風險控制的操作依據。",
            "url": latest.get("url", "#"),
            "sentiment": latest.get("sentiment", "Neutral")
        })

    risk_items = []
    for t in tweets:
        text = (t.get("text", "") + " " + t.get("summary", "")).lower()
        if t.get("sentiment") == "Bearish" or any(k in text for k in ["風險", "跌", "高估", "稀釋", "競爭", "砍單", "risk", "downside"]):
            risk_items.append({
                "date": t.get("date", "-"),
                "point": t.get("summary") or t.get("text", "")[:100],
                "url": t.get("url", "#")
            })
            if len(risk_items) >= 3:
                break

    return {
        "ticker": ticker,
        "thesis_story": thesis_story,
        "first_date": first.get("date", "-"),
        "latest_stance": latest.get("sentiment", "Neutral"),
        "total_mentions": total,
        "bull_ratio": bull_pct,
        "milestones": milestones[:3],
        "risks": risk_items
    }

def main():
    os.makedirs("data", exist_ok=True)
    raw_tweets = load_json(TWEETS_FILE, [])
    sentiment_cache = load_json(SENTIMENT_CACHE, {})
    if isinstance(sentiment_cache, list):
        sentiment_cache = {str(item.get("id") or item.get("tweet_id")): item for item in sentiment_cache if isinstance(item, dict)}

    ticker_tweets_map = {}

    for item in raw_tweets:
        if not isinstance(item, dict):
            continue
        t_id = str(item.get("id") or item.get("id_str") or item.get("tweet_id") or "")
        text = str(item.get("text") or item.get("full_text") or item.get("rawContent") or "")
        if not text:
            continue
        
        date_str = snowflake_to_iso(t_id) if t_id.isdigit() and len(t_id) >= 10 else str(item.get("created_at") or "")[:16]
        url = item.get("url") or f"https://twitter.com/aleabitoreddit/status/{t_id}"
        
        sent_info = sentiment_cache.get(t_id, {})
        sentiment = sent_info.get("sentiment", "Neutral")
        summary = sent_info.get("summary") or sent_info.get("summary_zh") or ""

        tickers = extract_tickers(text)
        tweet_entry = {
            "id": t_id,
            "text": text,
            "date": date_str,
            "url": url,
            "likes": int(item.get("favorite_count") or item.get("likes") or 0),
            "views": int(item.get("view_count") or item.get("views") or 0),
            "sentiment": sentiment,
            "summary": summary
        }

        for sym in tickers:
            if sym not in ticker_tweets_map:
                ticker_tweets_map[sym] = []
            ticker_tweets_map[sym].append(tweet_entry)

    thesis_database = {}
    print(f"🧠 正在分析 {len(ticker_tweets_map)} 檔個股論點 (LLM 模式: {'已啟用' if GEMINI_API_KEY else '啟發式降級模式'})...", flush=True)

    for ticker, tweets in ticker_tweets_map.items():
        if len(tweets) >= 1:
            thesis = None
            if GEMINI_API_KEY:
                thesis = call_gemini_for_thesis(ticker, tweets)
                time.sleep(0.5) # 遵守速率限制
            
            if not thesis:
                thesis = build_heuristic_thesis(ticker, tweets)
                
            if thesis:
                thesis_database[ticker] = thesis

    with open(OUTPUT_THESIS_FILE, "w", encoding="utf-8") as f:
        json.dump(thesis_database, f, ensure_ascii=False, indent=2)

    print(f"✅ AI 個股深度論點庫生成完畢，已存入 {OUTPUT_THESIS_FILE} (收錄 {len(thesis_database)} 檔)", flush=True)

if __name__ == "__main__":
    main()
