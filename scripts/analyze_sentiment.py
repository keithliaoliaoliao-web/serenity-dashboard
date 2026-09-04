import json
import os
import re
import sys
import time
from datetime import datetime
import requests

# ==========================================
# 參數設定區 (Serenity Tracker)
# ==========================================
TWEETS_FILE = "data/tweets.json"
CACHE_FILE = "data/sentiment_cache.json"

# 每次排程執行的最大分析則數 (可透過環境變數 TOTAL_TARGET 覆蓋)
TOTAL_TARGET = int(os.environ.get("TOTAL_TARGET", 50))

# 是否分析未提及單一 $股票的大盤/總經推文 (開啟即可讓分析量突破 71% 往 100% 推進)
ANALYZE_MACRO_TWEETS = True

# Twitter Snowflake 紀元起點 (2010-11-04 01:42:54.657 UTC)
TWITTER_EPOCH = 1288834974657

# Gemini API 金鑰
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

def log(msg):
    """即時強制輸出日誌"""
    print(msg, flush=True)

def get_tweet_timestamp(tweet):
    """利用 Snowflake 演算法或發布時間取得時間戳，確保由新到舊排序"""
    t_id = str(tweet.get("id") or tweet.get("id_str") or "0").strip()
    if t_id.isdigit() and len(t_id) >= 10:
        return (int(t_id) >> 22) + TWITTER_EPOCH
    
    # 備援：解析 created_at 字串
    created_at = tweet.get("created_at") or tweet.get("createdAt") or tweet.get("date") or ""
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0

def extract_tickers(text):
    """萃取推文中的美股代號"""
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Za-z]{1,6})\b", text)
    blacklist = {
        "USD", "USDT", "BTC", "ETH", "CAD", "EUR", "ATH", "CEO", "CFO", "CTO",
        "AI", "FOMC", "FED", "CPI", "PPI", "GDP", "DD", "EOD", "YOLO", "NEW",
        "BUY", "SELL", "HOLD", "CALL", "PUT", "AND", "THE", "TECH", "EV"
    }
    return sorted(list(set(t.upper() for t in matches if t.upper() not in blacklist and t.isalpha())))

def load_data():
    """載入推文庫與既有情緒快取"""
    if not os.path.exists(TWEETS_FILE):
        log(f"⚠️ 找不到推文檔案: {TWEETS_FILE}")
        return [], {}
        
    with open(TWEETS_FILE, "r", encoding="utf-8") as f:
        tweets = json.load(f)
        if isinstance(tweets, dict):
            for k in ["tweets", "data", "statuses", "results"]:
                if k in tweets and isinstance(tweets[k], list):
                    tweets = tweets[k]
                    break
            if isinstance(tweets, dict):
                tweets = list(tweets.values())

    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                raw_cache = json.load(f)
                if isinstance(raw_cache, dict):
                    cache = raw_cache
                elif isinstance(raw_cache, list):
                    for item in raw_cache:
                        if isinstance(item, dict):
                            t_id = str(item.get("id") or item.get("tweet_id") or "")
                            if t_id:
                                cache[t_id] = item
        except Exception as e:
            log(f"⚠️ 讀取快取檔案異常: {e}")
            cache = {}

    return tweets, cache

def save_cache(cache):
    """安全儲存快取檔案"""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def call_gemini_api(api_key, prompt_text):
    """採用原生 REST API 調用 Gemini，具備多模型自動降級備援"""
    candidate_models = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-pro"
    ]
    
    clean_key = api_key.strip().replace('"', '').replace("'", "")
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    for model in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
        try:
            res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=20)
            if res.status_code == 200:
                data = res.json()
                if "candidates" in data and data["candidates"]:
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return True, raw_text, model
            elif res.status_code == 429:
                log(f"  ⚠️ 模型 {model} 遭遇頻率限制 (429)，等待重試...")
                time.sleep(2)
        except Exception:
            pass

    return False, "", ""

def parse_ai_response(response_text):
    """安全解析 AI 回傳的 JSON 結構"""
    try:
        clean = response_text.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
        data = json.loads(clean)
        
        sentiment = data.get("sentiment", "Neutral")
        if "多" in sentiment or "Bull" in sentiment:
            sentiment = "Bullish"
        elif "空" in sentiment or "Bear" in sentiment:
            sentiment = "Bearish"
        else:
            sentiment = "Neutral"

        return {
            "sentiment": sentiment,
            "summary": data.get("summary", "").strip(),
            "translation_zh": data.get("translation_zh", "").strip()
        }
    except Exception:
        return {
            "sentiment": "Neutral",
            "summary": "觀點記錄",
            "translation_zh": ""
        }

def main():
    log("🚀 開始執行 Serenity 貼文 AI 情感分析與觀點提煉...")

    if not GEMINI_API_KEY:
        log("❌ 錯誤：未偵測到 GEMINI_API_KEY 環境變數，請在 GitHub Secrets 中配置。")
        sys.exit(1)

    tweets, cache = load_data()
    total_tweets_count = len(tweets)
    log(f"📊 總推文數: {total_tweets_count} 則 | 目前已分析快取數: {len(cache)} 則")

    # 1. 篩選尚未分析的推文
    pending_tweets = []
    for t in tweets:
        t_id = str(t.get("id") or t.get("id_str") or t.get("tweet_id") or "").strip()
        if not t_id or t_id in cache:
            continue
        
        text = t.get("text") or t.get("full_text") or ""
        if not text:
            continue

        tickers = extract_tickers(text)
        # 若未含個股標的，且未開啟大盤總經分析開關，則略過
        if not tickers and not ANALYZE_MACRO_TWEETS:
            continue

        pending_tweets.append(t)

    # 2. 【核心升級】：嚴格按發布時間「由新到舊」降冪排序，確保新推文絕對優先分析
    pending_tweets.sort(key=get_tweet_timestamp, reverse=True)

    log(f"🔍 待分析推文總數: {len(pending_tweets)} 則 (已依時間排序，新推文優先)")

    if not pending_tweets:
        log("✅ 所有符合條件的最新推文均已在快取中，無須重複分析。")
        return

    # 3. 擷取本次處理批次 (新推文在前)
    process_batch = pending_tweets[:TOTAL_TARGET]
    log(f"⚡ 本次預計分析批次: {len(process_batch)} 則推文 (上限: {TOTAL_TARGET})...")

    success_count = 0
    for idx, t in enumerate(process_batch, 1):
        t_id = str(t.get("id") or t.get("id_str") or t.get("tweet_id") or "").strip()
        text = t.get("text") or t.get("full_text") or ""
        tickers = extract_tickers(text)
        ticker_label = ", ".join([f"${s}" for s in tickers]) if tickers else "美股大盤/總經"

        prompt = f"""
你是一位專業的美股社群量化分析師。請分析以下推文內容，針對其投資觀點產出 JSON 格式：
推文內容：
\"\"\"{text}\"\"\"

請回傳標準 JSON 格式（不要包含額外對話）：
{{
  "sentiment": "Bullish 或 Bearish 或 Neutral",
  "summary": "以繁體中文撰寫 25 字以內的精煉觀點重點摘要（明確提及看多、看空、觀望或特定數據）",
  "translation_zh": "流暢且符合台灣財經用語的完整繁體中文翻譯"
}}
"""
        ok, res_text, model_used = call_gemini_api(GEMINI_API_KEY, prompt)
        if ok and res_text:
            parsed = parse_ai_response(res_text)
            cache[t_id] = {
                "id": t_id,
                "tweet_id": t_id,
                "sentiment": parsed["sentiment"],
                "summary": parsed["summary"],
                "translation_zh": parsed["translation_zh"],
                "analyzed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            success_count += 1
            log(f"  [{idx}/{len(process_batch)}] ✅ ID: {t_id} ({ticker_label}) ➔ 【{parsed['sentiment']}】 {parsed['summary']}")
            
            # 每成功分析 5 筆立即存檔一次，確保中途逾時不丟失資料
            if success_count % 5 == 0:
                save_cache(cache)
        else:
            log(f"  [{idx}/{len(process_batch)}] ⚠️ ID: {t_id} 分析失敗或跳過")

        # 適度間隔，遵守 API 速率限制
        time.sleep(1.2)

    # 4. 寫入最終快取資料庫
    save_cache(cache)
    coverage_pct = round((len(cache) / total_tweets_count) * 100, 1) if total_tweets_count else 0
    log(f"🎉 本次分析作業完成！成功分析: {success_count} 則")
    log(f"📈 目前最新 AI 分析總進度: {len(cache)} / {total_tweets_count} ({coverage_pct}%)")

if __name__ == "__main__":
    main()
