"""Gemini 呼叫小工具：自動挑選可用模型、遇到限流會等待重試、強制回傳 JSON。"""
import json
import os
import re
import time

import requests

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
_EXCLUDE = ("vision", "embedding", "tts", "image", "live", "audio", "robotics",
            "computer-use", "learnlm", "gemma", "aqa", "imagen", "veo")
_FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
# 最新版本通常最擠、額度最緊，所以優先用這幾個穩定的，名單裡沒有才輪到其他
_PREFERRED = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite"]
MAX_MODELS_PER_CALL = 5


def _log(msg):
    print(msg, flush=True)


def _score(name):
    low = name.lower()
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", low)
    score = (float(m.group(1)) if m else 0) * 100
    if "flash" in low:
        score += 50          # 速度快、免費額度較寬鬆
    if "lite" in low:
        score -= 20
    if "preview" in low or "exp" in low:
        score -= 60          # 優先使用穩定版
    return score


def list_models(key):
    found = []
    token = None
    for _ in range(3):
        params = {"pageSize": 200}
        if token:
            params["pageToken"] = token
        try:
            res = requests.get(f"{API_ROOT}/models", params=params,
                               headers={"x-goog-api-key": key}, timeout=15)
        except Exception as e:
            _log(f"⚠️ 查詢模型清單失敗: {e}")
            break
        if res.status_code != 200:
            _log(f"⚠️ 查詢模型清單失敗: HTTP {res.status_code}")
            break
        data = res.json()
        for m in data.get("models", []):
            name = m.get("name", "").replace("models/", "")
            if ("generateContent" in m.get("supportedGenerationMethods", [])
                    and "gemini" in name.lower()
                    and not any(x in name.lower() for x in _EXCLUDE)):
                found.append(name)
        token = data.get("nextPageToken")
        if not token:
            break
    found.sort(key=_score, reverse=True)
    pinned = os.environ.get("GEMINI_MODEL", "").strip()
    head = ([pinned] if pinned else []) + [m for m in _PREFERRED if m in found]
    return list(dict.fromkeys(head + found + _FALLBACK_MODELS))


def _parse_json(text):
    clean = (text or "").strip()
    clean = re.sub(r"^```[a-zA-Z]*\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean).strip()
    return json.loads(clean)


class GeminiClient:
    def __init__(self, api_key):
        self.key = api_key.strip().replace('"', "").replace("'", "")
        self.models = list_models(self.key)
        self.dead = set()       # 本次執行中確定不能用的模型（塞車、額度用完），不再浪費時間重試
        _log(f"📡 模型使用順序（前 4 名）: {self.models[:4]}")

    def _disable(self, model, reason):
        self.dead.add(model)
        _log(f"  🚫 {model} 本次先停用（{reason}），改用下一個模型")

    def generate_json(self, prompt, schema=None, temperature=0.2):
        """回傳 (status, payload, model)。
        status: "ok"（payload 是解析後的 dict）、"blocked"（被安全審查擋下）、"error"（payload 是錯誤說明）"""
        last_error = "所有模型本次都暫時無法使用"
        tried = 0
        for model in self.models:
            if model in self.dead:
                continue
            if tried >= MAX_MODELS_PER_CALL:
                break
            tried += 1
            use_schema = schema is not None
            for attempt in range(2):
                gen_cfg = {"temperature": temperature, "responseMimeType": "application/json"}
                if use_schema:
                    gen_cfg["responseSchema"] = schema
                body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
                try:
                    res = requests.post(f"{API_ROOT}/models/{model}:generateContent",
                                        json=body, headers={"x-goog-api-key": self.key}, timeout=60)
                except Exception as e:
                    last_error = f"[{model}] 連線失敗: {e}"
                    if attempt == 0:
                        time.sleep(3)
                        continue
                    self._disable(model, "連線失敗")
                    break

                if res.status_code == 200:
                    data = res.json()
                    block = (data.get("promptFeedback") or {}).get("blockReason")
                    cands = data.get("candidates") or []
                    if block or not cands:
                        return "blocked", block or "no candidates", model
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    text = parts[0].get("text") if parts else ""
                    try:
                        return "ok", _parse_json(text), model
                    except Exception:
                        last_error = f"[{model}] 回傳不是有效的 JSON"
                        continue

                try:
                    msg = res.json().get("error", {}).get("message", "")
                except Exception:
                    msg = res.text[:150]
                last_error = f"[{model}] HTTP {res.status_code}: {msg[:120]}"

                if res.status_code == 429:
                    low = msg.lower()
                    if "per day" in low or "perday" in low or "daily" in low:
                        self._disable(model, "今日額度已用完")
                        break
                    if attempt == 0:
                        time.sleep(15)       # 每分鐘次數限制，等一下再試一次
                        continue
                    self._disable(model, "429 限流")
                    break
                if res.status_code in (500, 502, 503, 504):
                    if attempt == 0:
                        time.sleep(5)
                        continue
                    self._disable(model, f"HTTP {res.status_code} 伺服器忙碌")
                    break
                if res.status_code == 400 and use_schema:
                    use_schema = False       # 這個模型不吃格式限制，改成純 JSON 模式再試
                    continue
                self._disable(model, f"HTTP {res.status_code}")   # 金鑰或模型不存在
                break
        return "error", last_error, ""
