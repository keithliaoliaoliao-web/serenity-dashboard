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

# 每次排程執行的最大分析則數 (預設 50，可依需求調大)
TOTAL_TARGET = int(os.environ.get("TOTAL_TARGET", 50))

# 是否分析未包含特定 $股票代號 的大盤/總經推文 (開啟以推進 71% 往 100% 邁進)
ANALYZE_MACRO_TWEETS = True

# Twitter Snowflake 紀元起點 (2010-11-04 01:42:54.657 UTC)
TWITTER_EPOCH = 1288834974657

# Gemini API 金鑰
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

def log(msg):
    """即時強制輸出日誌至控制台"""
    print(msg, flush=True)

def get_tweet_timestamp(tweet):
    """利用 Snowflake 演算法或發布時間取得時間戳，確保由新到舊排序"""
    t_id = str(tweet.get("id") or tweet.get("id_str") or "0").strip()
    if t_id.isdigit() and len(t_id) >= 10:
        return (int(t_id) >> 22) + TWITTER_EPOCH
    
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
    """載入本地推文庫與快取"""
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

def fetch_available_gemini_models(clean_key):
    """動態向 Google AI Studio 查詢當前金鑰可用之模型清單並依穩定性排序"""
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={clean_key}"
    headers = {"x-goog-api-key": clean_key}
    models = []
    
    try:
        res = requests.get(list_url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            raw_models = data.get("models", [])
            for m in raw_models:
                methods = m.get("supportedGenerationMethods", [])
                name = m.get("name", "").replace("models/", "")
                if "generateContent" in methods and "gemini" in name.lower():
                    if not any(x in name.lower() for x in ["vision", "embedding", "tts"]):
                        models.append(name)
    except Exception as e:
        log(f"⚠️ 動態探測模型時發生異常: {e}")

    # 權重評分排序器 (優先使用 Flash 系列以追求高速度與穩定度)
    def model_rank(name):
        score = 0
        low = name.lower()
        if "flash" in low:
            score += 50
        if "2.5" in low:
            score += 40
        elif "2.0" in low:
            score += 30
        elif "1.5" in low:
            score += 20
        if "pro" in low:
            score += 10
        return score

    models.sort(key=model_rank, reverse=True)

    # 安全預設備援名單
    fallback_defaults = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-pro"
    ]
    return list(dict.fromkeys(models + fallback_defaults))

def call_gemini_api(api_key, prompt_text, available_models):
    """採用標準 REST API 執行生成，附帶清晰的錯誤日誌輸出"""
    clean_key = api_key.strip().replace('"', '').replace("'", "")
    
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.2
        }
    }

    last_error_detail = ""

    for model in available_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": clean_key
        }

        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    candidate = data["candidates"][0]
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])
                    if parts and "text" in parts[0]:
                        return True, parts[0]["text"], model
            elif res.status_code == 429:
                last_error_detail = f"[{model}] 觸發頻率限制 (HTTP 429)"
                time.sleep(1.5)
            else:
                err_msg = ""
                try:
                    err_json = res.json()
                    err_msg = err_json.get("error", {}).get("message", "")
                except Exception:
                    err_msg = res.text[:120]
                last_error_detail = f"[{model}] HTTP {res.status_code}: {err_msg}"
        except Exception as conn_err:
            last_error_detail = f"[{model}] 連線失敗: {conn_err}"

    return False, last_error_detail, ""

def parse_ai_response(response_text):
    """健全解析 AI 回傳的 JSON 結構 (支援 Markdown 區塊與鬆散字串)"""
    clean = response_text.strip()
    
    # 移除可能的 Markdown 標記
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
    clean = clean.strip()

    try:
        data = json.loads(clean)
        sentiment = str(data.get("sentiment", "Neutral"))
        if any(w in sentiment for w in ["多", "Bull", "看多"]):
            sentiment = "Bullish"
        elif any(w in sentiment for w in ["空", "Bear", "看空"]):
            sentiment = "Bearish"
        else:
            sentiment = "Neutral"

        return {
            "sentiment": sentiment,
            "summary": str(data.get("summary", "")).strip() or "觀點記錄",
            "translation_zh": str(data.get("translation_zh", "")).strip()
        }
    except Exception:
        # 若 AI 未完全遵照 JSON 格式，以正則表達式強制救援
        sentiment = "Neutral"
        if re.search(r"bullish|看多|偏多", clean, re.IGNORECASE):
            sentiment = "Bullish"
        elif re.search(r"bearish|看空|偏空", clean, re.IGNORECASE):
            sentiment = "Bearish"

        summary_match = re.search(r'["\']?summary["\']?\s*:\s*["\'](.*?)["\']', clean)
        summary = summary_match.group(1) if summary_match else clean[:40]

        return {
            "sentiment": sentiment,
            "summary": summary.strip(),
            "translation_zh": clean
        }

def main():
    log("🚀 開始執行 Serenity 貼文 AI 情感分析與觀點提煉...")

    if not GEMINI_API_KEY:
        log("❌ 錯誤：未偵測到 GEMINI_API_KEY 環境變數，請在 GitHub Secrets 中配置。")
        sys.exit(1)

    clean_key = GEMINI_API_KEY.strip().replace('"', '').replace("'", "")
    available_models = fetch_available_gemini_models(clean_key)
    log(f"📡 已動態偵測並排序可用模型: {available_models[:4]}")

    tweets, cache = load_data()
    total_tweets_count = len(tweets)
    log(f"📊 總推文數: {total_tweets_count} 則 | 目前已分析快取數: {len(cache)} 則")

    # 1. 篩選未分析的推文
    pending_tweets = []
    for t in tweets:
        t_id = str(t.get("id") or t.get("id_str") or t.get("tweet_id") or "").strip()
        if not t_id or t_id in cache:
            continue
        
        text = t.get("text") or t.get("full_text") or ""
        if not text:
            continue

        tickers = extract_tickers(text)
        if not tickers and not ANALYZE_MACRO_TWEETS:
            continue

        pending_tweets.append(t)

    # 2. 嚴格依時間由新到舊排序，新推文享有最高處理優先權
    pending_tweets.sort(key=get_tweet_timestamp, reverse=True)

    log(f"🔍 待分析推文總數: {len(pending_tweets)} 則 (已依時間排序，最新推文優先)")

    if not pending_tweets:
        log("✅ 所有最新推文均已在快取中，無須重複分析。")
        return

    # 3. 處理本次批次
    process_batch = pending_tweets[:TOTAL_TARGET]
    log(f"⚡ 本次預計分析批次: {len(process_batch)} 則推文 (上限: {TOTAL_TARGET})...")

    success_count = 0
    for idx, t in enumerate(process_batch, 1):
        t_id = str(t.get("id") or t.get("id_str") or t.get("tweet_id") or "").strip()
        text = t.get("text") or t.get("full_text") or ""
        tickers = extract_tickers(text)
        ticker_label = ", ".join([f"${s}" for s in tickers]) if tickers else "美股大盤/總經"

        prompt = f"""
你是一位專業的美股社群量化分析師。請分析以下推文內容，判斷投資立場並產出標準 JSON 格式：
推文內容：
{json.dumps(text, ensure_ascii=False)}

請嚴格回傳符合以下鍵名的標準 JSON 物件，請勿附加任何解釋文字：
{{
  "sentiment": "Bullish 或 Bearish 或 Neutral",
  "summary": "以繁體中文撰寫 25 字以內的觀點重點摘要（明確提及立場、標的或關鍵點位）",
  "translation_zh": "符合台灣財經用語的流暢繁體中文翻譯"
}}
"""
        ok, result_text, model_used = call_gemini_api(clean_key, prompt, available_models)
        
        if ok and result_text:
            parsed = parse_ai_response(result_text)
            cache[t_id] = {
                "id": t_id,
                "tweet_id": t_id,
                "sentiment": parsed["sentiment"],
                "summary": parsed["summary"],
                "translation_zh": parsed["translation_zh"],
                "analyzed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            success_count += 1
            log(f"  [{idx}/{len(process_batch)}] ✅ ID: {t_id} ({ticker_label}) ➔ 【{parsed['sentiment']}】 {parsed['summary']} (via {model_used})")
            
            # 每成功 5 筆立即存檔
            if success_count % 5 == 0:
                save_cache(cache)
        else:
            # 透明化印出失敗原因，方便隨時檢視
            log(f"  [{idx}/{len(process_batch)}] ⚠️ ID: {t_id} 分析未成功: {result_text}")

        # 適度間隔保護 API 速率限制
        time.sleep(1.0)

    # 4. 寫入最終快取檔案
    save_cache(cache)
    coverage_pct = round((len(cache) / total_tweets_count) * 100, 1) if total_tweets_count else 0
    log(f"🎉 本次批次作業完成！成功分析: {success_count} 則")
    log(f"📈 目前最新 AI 分析總進度: {len(cache)} / {total_tweets_count} ({coverage_pct}%)")

if __name__ == "__main__":
    main()
