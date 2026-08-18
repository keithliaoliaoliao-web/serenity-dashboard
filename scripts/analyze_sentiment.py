import json
import os
import re
import google.generativeai as genai

TWEETS_FILE = "data/tweets.json"
CACHE_FILE = "data/sentiment_cache.json"

API_KEY = os.environ.get("GEMINI_API_KEY")

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_tickers(text):
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Z]{1,5})\b", text.upper())
    blacklist = {"USD", "CAD", "EUR", "ATH", "CEO", "AI", "FOMC", "FED", "CPI", "GDP"}
    return [t for t in set(matches) if t not in blacklist]

def analyze_batch(texts_to_analyze):
    if not API_KEY:
        print("⚠️ 未檢測到 GEMINI_API_KEY，略過 AI 分析")
        return {}

    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = """
你是一位精通美股交易與社群語境的資深分析師。請分析以下 Twitter 貼文：
1. 判斷對標的 ($TICKER) 的交易情緒："Bullish" (看多/買進), "Bearish" (看空/警戒/獲利了結), 或 "Neutral" (客觀討論/迷因/問答)。
2. 將推文完整翻譯為道地、通順的【繁體中文】(translation_zh)，保留美股專業術語（例如 Call/Put、突破、支撐位等）。
3. 提供 15 字以內的【繁體中文核心觀點摘要】(summary)。

待分析推文：
"""
    for item in texts_to_analyze:
        prompt += f"\nID: {item['id']}\nText: {item['text']}\n---"

    prompt += """
請以純 JSON 格式回傳，格式範例如下：
{
  "tweet_id": {
    "sentiment": "Bullish",
    "summary": "突破頸線看好後續動能",
    "translation_zh": "這就是為什麼我買了 15 萬美元的 $UPWK..."
  }
}
不要輸出任何 Markdown 區塊外的文字。
"""

    try:
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        raw_text = re.sub(r"^```json\s*", "", raw_text)
        raw_text = re.sub(r"^```\s*", "", raw_text)
        raw_text = re.sub(r"```$", "", raw_text).strip()
        return json.loads(raw_text)
    except Exception as e:
        print(f"Gemini API 呼叫失敗: {e}")
        return {}

def run_sentiment_pipeline(batch_limit=40):
    raw_data = load_json(TWEETS_FILE, [])
    if isinstance(raw_data, dict):
        raw_data = raw_data.get("tweets", raw_data.get("data", list(raw_data.values())))

    sentiment_cache = load_json(CACHE_FILE, {})

    unprocessed = []
    for item in raw_data:
        t_id = str(item.get("id") or item.get("id_str") or item.get("tweet_id") or "")
        text = item.get("text") or item.get("rawContent") or item.get("full_text") or ""
        if not t_id or not text:
            continue
        
        # 判斷是否缺少情緒或繁中翻譯
        cached = sentiment_cache.get(t_id)
        needs_analysis = not cached or "translation_zh" not in cached
        
        if extract_tickers(text) and needs_analysis:
            unprocessed.append({"id": t_id, "text": text})

    print(f"待分析與翻譯之個股推文數: {len(unprocessed)}")
    if not unprocessed:
        print("所有個股推文均已完成 AI 分析與繁中翻譯。")
        return

    to_process = unprocessed[:batch_limit]
    print(f"正在使用 Gemini 分析與翻譯最新 {len(to_process)} 則推文...")

    results = analyze_batch(to_process)
    for t_id, res in results.items():
        if isinstance(res, dict) and "sentiment" in res:
            sentiment_cache[str(t_id)] = {
                "sentiment": res.get("sentiment", "Neutral"),
                "summary": res.get("summary", ""),
                "translation_zh": res.get("translation_zh", "")
            }

    save_json(CACHE_FILE, sentiment_cache)
    print(f"✅ 快取已更新，目前共快取 {len(sentiment_cache)} 筆資料。")

if __name__ == "__main__":
    run_sentiment_pipeline()
