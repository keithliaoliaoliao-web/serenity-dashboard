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
                data = json.load(f)
                if isinstance(data, dict):
                    data = data.get("tweets", data.get("data", list(data.values())))
                return data
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

def extract_tweet_id(item):
    for k in ["id", "id_str", "tweet_id", "tweetId", "rest_id"]:
        if k in item and item[k]:
            return str(item[k])
    url = item.get("url") or item.get("permanentUrl") or ""
    if url:
        m = re.search(r"status/(\d+)", str(url))
        if m: return m.group(1)
    return ""

def extract_tweet_text(item):
    for k in ["text", "rawContent", "full_text", "content"]:
        if k in item and item[k]:
            return str(item[k])
    legacy = item.get("legacy") or {}
    if isinstance(legacy, dict) and "full_text" in legacy:
        return str(legacy["full_text"])
    return ""

def analyze_batch(texts_to_analyze):
    if not API_KEY:
        print("⚠️ 未檢測到 GEMINI_API_KEY，略過 AI 分析")
        return {}

    genai.configure(api_key=API_KEY)
    
    # 依序嘗試可用模型
    model_names = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    model = None
    for m_name in model_names:
        try:
            model = genai.GenerativeModel(m_name)
            break
        except Exception:
            continue

    prompt = """
你是一位資深美股分析師。請分析以下 Twitter 貼文：
1. 判斷對標的 ($TICKER) 的交易情緒："Bullish" (看多/買進), "Bearish" (看空/獲利了結), 或 "Neutral" (中立/客觀分析)。
2. 將推文完整翻譯為道地繁體中文 (translation_zh)。
3. 提供 15 字以內的繁體中文核心觀點摘要 (summary)。

待分析推文：
"""
    for item in texts_to_analyze:
        prompt += f"\nID: {item['id']}\nText: {item['text']}\n---"

    prompt += "\n\n請僅輸出標準 JSON 格式，不要包含任何 markdown 語法外的文字。"

    try:
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        raw_text = re.sub(r"^```json\s*", "", raw_text)
        raw_text = re.sub(r"^```\s*", "", raw_text)
        raw_text = re.sub(r"```$", "", raw_text).strip()
        return json.loads(raw_text)
    except Exception as e:
        print(f"Gemini API 調用失敗: {e}")
        return {}

def run_sentiment_pipeline(batch_limit=50):
    raw_data = load_json(TWEETS_FILE, [])
    sentiment_cache = load_json(CACHE_FILE, {})

    unprocessed = []
    for item in raw_data:
        t_id = extract_tweet_id(item)
        text = extract_tweet_text(item)
        if not t_id or not text:
            continue
        
        cached = sentiment_cache.get(t_id)
        needs_analysis = not cached or "translation_zh" not in cached
        
        if extract_tickers(text) and needs_analysis:
            unprocessed.append({"id": t_id, "text": text})

    print(f"待分析推文數: {len(unprocessed)}")
    if not unprocessed:
        print("所有推文皆已快取。")
        return

    to_process = unprocessed[:batch_limit]
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
