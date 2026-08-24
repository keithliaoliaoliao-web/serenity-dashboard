import json
import os
import time
import requests

# ==========================================
# 參數設定
# ==========================================
OUTPUT_FILE = "data/tweets.json"
TARGET_HANDLE = os.environ.get("TARGET_HANDLE", "aleabitoreddit")

# 遠端推文備援資料來源 (含 GitHub Raw 與 jsDelivr CDN)
DATA_SOURCES = [
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json",
    "https://cdn.jsdelivr.net/gh/yan-labs/serenity-aleabitoreddit@main/data/aleabitoreddit_tweets.json",
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/master/data/aleabitoreddit_tweets.json"
]

def fetch_tweets():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    print(f"🔄 正在為 @{TARGET_HANDLE} 同步歷史推文資料庫...", flush=True)

    tweets = []
    # 依序嘗試多個來源
    for url in DATA_SOURCES:
        try:
            print(f"  🌐 正在連接資料來源: {url[:60]}...", flush=True)
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    tweets = data
                    print(f"  ✅ 成功從遠端載入 {len(tweets)} 則推文！", flush=True)
                    break
                elif isinstance(data, dict) and len(data) > 0:
                    tweets = list(data.values())
                    print(f"  ✅ 成功從遠端字典格式轉換 {len(tweets)} 則推文！", flush=True)
                    break
        except Exception as e:
            print(f"  ⚠️ 連線來源失敗，嘗試下一個備用來源: {e}", flush=True)
            time.sleep(1)

    # 防清空熔斷保護：若抓取為空且本地已有資料，保留本地資料
    if not tweets and os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                local_data = json.load(f)
                if len(local_data) > 0:
                    print(f"🛡️ 遠端暫時無法連線，啟用熔斷保護：保留本地現存 {len(local_data)} 則推文。", flush=True)
                    return
        except Exception:
            pass

    if tweets:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(tweets, f, ensure_ascii=False, indent=2)
        print(f"💾 推文資料庫已成功儲存至 {OUTPUT_FILE} (共 {len(tweets)} 則)", flush=True)
    else:
        print("❌ 警告：所有資料來源皆連線失敗，請檢查網路連線。", flush=True)

if __name__ == "__main__":
    fetch_tweets()
