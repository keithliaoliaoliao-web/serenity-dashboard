import json
import os
import re
import time
from datetime import datetime
import google.generativeai as genai

TWEETS_FILE = "data/tweets.json"
CACHE_FILE = "data/sentiment_cache.json"

API_KEY = os.environ.get("GEMINI_API_KEY")

def load_tweets(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for key in ["tweets", "data", "statuses", "results"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return list(data.values())
            return []
    except Exception as e:
        print(f"讀取推文失敗: {e}")
        return []

def load_cache(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                cache_dict = {}
                for item in data:
                    if isinstance(item, dict):
                        t_id = str(item.get("id") or item.get("tweet_id") or "")
                        if t_id:
                            cache_dict[t_id] = item
                return cache_dict
            return {}
    except Exception as e:
        print(f"讀取快取失敗: {e}")
        return {}

def save_json(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_tickers(text):
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Z]{1,5})\b", text.upper())
    blacklist = {"USD", "CAD", "EUR", "ATH", "CEO", "AI", "FOMC", "FED", "CPI", "GDP", "DD", "EOD", "YOLO"}
    return [t for t in set(matches) if t not in blacklist]

def extract_tweet_id(item):
    for k in ["id", "id_str", "tweet_id", "tweetId", "rest_id", "conversation_id"]:
        if k in item and item[k]:
            return str(item[k]).strip()
    url = item.get("url") or item.get("permanentUrl") or item.get("link") or ""
    if url:
        m = re.search(r"status/(\d+)", str(url))
        if m: return m.group(1).strip()
    return ""

def extract_tweet_text(item):
    for k in ["text", "rawContent", "full_text", "content", "tweet", "body"]:
        if k in item and item[k]:
            return str(item[k])
    legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
    if "full_text" in legacy:
        return str(legacy["full_text"])
    return ""

def parse_sort_key(item):
    raw_date = None
    for k in ["date", "created_at", "createdAt", "timestamp", "datetime", "time"]:
        if k in item and item[k]:
            raw_date = item[k]
            break
    if not raw_date:
        legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
        raw_date = legacy.get("created_at")

    if not raw_date:
        return ""

    if isinstance(raw_date, (int, float)):
        try:
            dt = datetime.fromtimestamp(raw_date / 1000.0 if raw_date > 1e11 else raw_date)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    s = str(raw_date).strip()
    if s.isdigit():
        try:
            dt = datetime.fromtimestamp(float(s) / 1000.0 if float(s) > 1e11 else float(s))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    try:
        if "T" in s or "+" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    try:
        if len(s.split()) >= 6:
            dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mth, d = m.groups()
        return f"{int(y):04d}-{int(mth):02d}-{int(d):02d}"

    return s

def get_dynamic_model():
    """自動偵測此 API Key 可用的所有模型，並挑選最適模型"""
    if not API_KEY:
        print("❌ 錯誤：未檢測到 GEMINI_API_KEY 環境變數。")
        return None

    genai.configure(api_key=API_KEY)

    try:
        models = list(genai.list_models())
        supported = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        print(f"📋 該 API Key 可用的模型清單: {supported}")
    except Exception as e:
        print(f"⚠️ 無法動態列出模型: {e}")
        supported = []

    preferred = [
        "models/gemini-2.0-flash",
        "models/gemini-1.5-flash",
        "models/gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-8b",
        "models/gemini-1.5-pro",
        "models/gemini-1.0-pro"
    ]

    selected_model_name = None
    for pref in preferred:
        if pref in supported:
            selected_model_name = pref
            break

    if not selected_model_name and supported:
        flash_candidates = [m for m in supported if "flash" in m]
        selected_model_name = flash_candidates[0] if flash_candidates else supported[0]

    if not selected_model_name:
        selected_model_name = "gemini-1.5-flash"

    # 去除 models/ 前綴以符合 GenerativeModel 初始化格式
    clean_name = selected_model_name.replace("models/", "")
    print(f"🎯 自動選定使用模型: {clean_name}")
    return genai.GenerativeModel(clean_name)

def analyze_sub_batch(model, items):
    prompt = """你是一位資深美股分析師。請分析以下 Twitter 貼文：
1. 判斷對標的 ($TICKER) 的交易情緒："Bullish" (看多/買進), "Bearish" (看空/警戒), 或 "Neutral" (中立/客觀分析)。
2. 將推文完整翻譯為繁體中文 (translation_zh)。
3. 提供 15 字以內的繁體中文核心觀點摘要 (summary)。

待分析推文：
"""
    for item in items:
        prompt += f"\nID: {item['id']}\nText: {item['text']}\n---"

    prompt += "\n\n請以標準 JSON 物件回傳（以推文 ID 作為 Key），不要包含任何 markdown 區塊外的文字。"

    try:
        try:
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
        except Exception:
            response = model.generate_content(prompt)

        raw_text = response.text.strip()
        raw_text = re.sub(r"^```json\s*", "", raw_text)
        raw_text = re.sub(r"^```\s*", "", raw_text)
        raw_text = re.sub(r"```$", "", raw_text).strip()
        return json.loads(raw_text)
    except Exception as e:
        print(f"❌ 本批次呼叫失敗: {e}")
        return {}

def run_sentiment_pipeline(total_target=30, chunk_size=10):
    model = get_dynamic_model()
    if not model:
        return

    raw_data = load_tweets(TWEETS_FILE)
    sentiment_cache = load_cache(CACHE_FILE)

    raw_data.sort(key=parse_sort_key, reverse=True)

    unprocessed = []
    for item in raw_data:
        t_id = extract_tweet_id(item)
        text = extract_tweet_text(item)
        if not t_id or not text:
            continue

        cached = sentiment_cache.get(t_id)
        needs_analysis = (
            not cached or 
            not isinstance(cached, dict) or 
            not cached.get("summary") or 
            not cached.get("translation_zh")
        )

        if extract_tickers(text) and needs_analysis:
            unprocessed.append({"id": t_id, "text": text})

    print(f"🔍 待分析個股推文總數: {len(unprocessed)} 則")
    if not unprocessed:
        print("所有最新推文均已在快取中。")
        return

    to_process = unprocessed[:total_target]
    print(f"🚀 本次將分批處理最新 {len(to_process)} 則推文（每批 {chunk_size} 則）...")

    added_count = 0
    for i in range(0, len(to_process), chunk_size):
        chunk = to_process[i:i + chunk_size]
        print(f"  正在分析第 {i + 1} ~ {i + len(chunk)} 則...")
        results = analyze_sub_batch(model, chunk)

        for item in chunk:
            t_id = item["id"]
            res = results.get(t_id) or results.get(str(t_id))
            if res and isinstance(res, dict):
                sentiment_cache[t_id] = {
                    "sentiment": res.get("sentiment", "Neutral"),
                    "summary": res.get("summary", ""),
                    "translation_zh": res.get("translation_zh", "")
                }
                added_count += 1
                print(f"    ✅ 已解析 [{t_id}]: {res.get('summary')}")

        time.sleep(1)

    save_json(CACHE_FILE, sentiment_cache)
    print(f"🎉 本次成功更新 {added_count} 則推文快取！目前總快取量: {len(sentiment_cache)} 則。")

if __name__ == "__main__":
    run_sentiment_pipeline(total_target=30, chunk_size=10)
