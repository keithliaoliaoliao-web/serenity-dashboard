"""共用工具：所有腳本共用同一套規則（時間換算、股票代號萃取、讀寫檔案），
避免各個檔案各做各的、結果互相對不上。"""
import json
import os
import re
from datetime import datetime, timezone

TARGET_HANDLE = "aleabitoreddit"

# Twitter Snowflake 紀元起點 (2010-11-04 01:42:54.657 UTC)
TWITTER_EPOCH = 1288834974657

# 推文錯別字自動校正
TICKER_ALIASES = {
    "APPL": "AAPL",
    "QLCM": "QCOM",
    "WLAC": "KLAC",
}

# 不是股票代號的常見縮寫（情緒分析、論點、網頁三邊共用同一份）
TICKER_BLACKLIST = {
    "USD", "USDT", "BTC", "ETH", "SOL", "CAD", "EUR", "ATH", "CEO", "CFO", "CTO",
    "AI", "FOMC", "FED", "CPI", "PPI", "GDP", "DD", "EOD", "YOLO", "NEW",
    "BUY", "SELL", "HOLD", "CALL", "PUT", "AND", "THE", "TECH", "EV",
    "RPI", "VNP",
}


def log(msg):
    print(msg, flush=True)


def snowflake_to_dt(tweet_id):
    """用推文 ID 算出精確的 UTC 時間（ID 是最可靠的時間來源）。"""
    try:
        t_id = int(str(tweet_id).strip())
    except (TypeError, ValueError):
        return None
    if t_id < (1 << 22):
        return None
    ms = (t_id >> 22) + TWITTER_EPOCH
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def snowflake_to_iso(tweet_id):
    dt = snowflake_to_dt(tweet_id)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def tweet_id_of(item):
    for k in ["id", "id_str", "tweet_id", "tweetId", "rest_id"]:
        if item.get(k):
            return str(item[k]).strip()
    url = item.get("url") or item.get("permanentUrl") or item.get("link") or ""
    m = re.search(r"status/(\d+)", str(url))
    return m.group(1) if m else ""


def tweet_text_of(item):
    for k in ["text", "full_text", "rawContent", "content", "tweet", "body", "message"]:
        if item.get(k):
            return str(item[k])
    legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
    return str(legacy.get("full_text") or "")


def extract_tickers(text):
    if not text:
        return []
    matches = re.findall(r"(?<!\w)\$([A-Za-z]{1,6})\b", text)
    out = set()
    for m in matches:
        sym = TICKER_ALIASES.get(m.upper().strip(), m.upper().strip())
        if sym not in TICKER_BLACKLIST and sym.isalpha():
            out.add(sym)
    return sorted(out)


def normalize_sentiment(raw):
    s = str(raw or "")
    low = s.lower()
    if "bull" in low or "多" in s:
        return "Bullish"
    if "bear" in low or "空" in s:
        return "Bearish"
    return "Neutral"


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"⚠️ 讀取 {path} 失敗: {e}")
        return default


def save_json(path, data, indent=None):
    """先寫暫存檔再替換，避免寫到一半被中斷而壞檔。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    seps = (",", ":") if indent is None else (",", ": ")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, separators=seps)
    os.replace(tmp, path)


def load_tweet_list(path):
    data = load_json(path, [])
    if isinstance(data, dict):
        for k in ["tweets", "data", "statuses", "results"]:
            if isinstance(data.get(k), list):
                return data[k]
        return list(data.values())
    return data if isinstance(data, list) else []


def load_sentiment_cache(path):
    data = load_json(path, {})
    if isinstance(data, list):
        return {str(i.get("id") or i.get("tweet_id")): i for i in data
                if isinstance(i, dict) and (i.get("id") or i.get("tweet_id"))}
    return data if isinstance(data, dict) else {}


def stance_for(entry, ticker):
    """某則推文對「某一檔股票」的立場。
    新版快取每檔股票各有立場；舊版快取只有整則推文一個立場。"""
    if not isinstance(entry, dict):
        return "Neutral"
    stances = entry.get("stances")
    if isinstance(stances, dict) and stances:
        return normalize_sentiment(stances.get(ticker, "Neutral"))
    return normalize_sentiment(entry.get("sentiment"))
