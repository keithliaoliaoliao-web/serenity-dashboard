"""Gemini 呼叫小工具：自動挑選可用模型、遇到限流會等待重試、強制回傳 JSON。"""
import json
import re
import time

import requests

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
_EXCLUDE = ("vision", "embedding", "tts", "image", "live", "audio", "robotics",
            "computer-use", "learnlm", "gemma", "aqa", "imagen", "veo")
_FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]


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
    return list(dict.fromkeys(found + _FALLBACK_MODELS))


def _parse_json(text):
    clean = (text or "").strip()
    clean = re.sub(r"^```[a-zA-Z]*\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean).strip()
    return json.loads(clean)


class GeminiClient:
    def __init__(self, api_key):
        self.key = api_key.strip().replace('"', "").replace("'", "")
        self.models = list_models(self.key)
        self.idx = 0
        _log(f"📡 可用模型（前 4 名）: {self.models[:4]}")

    def generate_json(self, prompt, schema=None, temperature=0.2):
        """回傳 (status, payload, model)。
        status: "ok"（payload 是解析後的 dict）、"blocked"（被安全審查擋下）、"error"（payload 是錯誤說明）"""
        last_error = "沒有可用模型"
        for i in range(self.idx, len(self.models)):
            model = self.models[i]
            use_schema = schema is not None
            for attempt in range(3):
                gen_cfg = {"temperature": temperature, "responseMimeType": "application/json"}
                if use_schema:
                    gen_cfg["responseSchema"] = schema
                body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
                try:
                    res = requests.post(f"{API_ROOT}/models/{model}:generateContent",
                                        json=body, headers={"x-goog-api-key": self.key}, timeout=90)
                except Exception as e:
                    last_error = f"[{model}] 連線失敗: {e}"
                    time.sleep(3)
                    continue

                if res.status_code == 200:
                    data = res.json()
                    block = (data.get("promptFeedback") or {}).get("blockReason")
                    cands = data.get("candidates") or []
                    if block or not cands:
                        return "blocked", block or "no candidates", model
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    text = parts[0].get("text") if parts else ""
                    try:
                        payload = _parse_json(text)
                    except Exception:
                        last_error = f"[{model}] 回傳不是有效的 JSON"
                        continue
                    self.idx = i
                    return "ok", payload, model

                if res.status_code in (429, 500, 502, 503, 504):
                    wait = 20 * (attempt + 1)
                    last_error = f"[{model}] HTTP {res.status_code}，等待 {wait} 秒後重試"
                    _log(f"  ⏳ {last_error}")
                    time.sleep(wait)
                    continue

                try:
                    msg = res.json().get("error", {}).get("message", "")
                except Exception:
                    msg = res.text[:150]
                last_error = f"[{model}] HTTP {res.status_code}: {msg}"
                if res.status_code == 400 and use_schema:
                    use_schema = False   # 這個模型不吃格式限制，改成純 JSON 模式再試一次
                    continue
                break   # 其他錯誤（金鑰、模型不存在）→ 換下一個模型
        return "error", last_error, ""
