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
    """呼叫 Gemini 進行批次分類"""
    if not API_KEY:
        print("⚠️ 未檢測到 GEMINI_API_KEY，略過 AI 分析")
        return {}

    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = """
你是一位資深美股交易員。請分析以下 Twitter 貼文對其提及之美股標的 ($TICKER) 的交易情緒。
回傳格式必須為標準 JSON 物件，以 id 作為 key，value 包含 sentiment ("Bullish", "Bearish", "Neutral") 與 繁體中文的簡短摘要 summary (15字以內)。

待分析推文列表：
"""
    for item in texts_to_analyze:
        prompt += f"\nID: {item['id']}\nText: {item['text']}\n---"

    prompt += "\n\n請僅輸出純 JSON 格式，不要加入額外的 markdown 解釋。"

    try:
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        raw_text = re.sub(r"^```json\s*", "", raw_text)
        raw_text = re.sub(r"```$", "", raw_text).strip()
        return json.loads(raw_text)
    except Exception as e:
        print(f"Gemini API 呼叫失敗: {e}")
        return {}

def run_sentiment_pipeline(batch_limit=30):
    raw_data = load_json(TWEETS_FILE, [])
    if isinstance(raw_data, dict):
        raw_data = raw_data.get("tweets", raw_data.get("data", list(raw_data.values())))

    sentiment_cache = load_json(CACHE_FILE, {})

    # 找出含 $TICKER 且尚未分析的推文 (優先處理最新推文)
    unprocessed = []
    for item in raw_data:
        t_id = str(item.get("id") or item.get("id_str") or item.get("tweet_id") or "")
        text = item.get("text") or item.get("full_text") or ""
        if not t_id or not text:
            continue
        if extract_tickers(text) and t_id not in sentiment_cache:
            unprocessed.append({"id": t_id, "text": text})

    print(f"總待分析個股推文數: {len(unprocessed)}")
    if not unprocessed:
        print("所有個股推文均已在快取中。")
        return

    # 每次最多分析 batch_limit 則，避免超出 rate limit
    to_process = unprocessed[:batch_limit]
    print(f"正在使用 Gemini 分析最新的 {len(to_process)} 則推文...")

    results = analyze_batch(to_process)
    for t_id, res in results.items():
        if isinstance(res, dict) and "sentiment" in res:
            sentiment_cache[str(t_id)] = {
                "sentiment": res.get("sentiment", "Neutral"),
                "summary": res.get("summary", "")
            }

    save_json(CACHE_FILE, sentiment_cache)
    print(f"✅ 快取已更新，目前共快取 {len(sentiment_cache)} 則推文情緒。")

if __name__ == "__main__":
    run_sentiment_pipeline()
