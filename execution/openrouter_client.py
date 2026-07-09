import json
import os
import time
import requests
from pathlib import Path
from typing import Dict, List


def _load_api_key() -> str:
    auth_path = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    if auth_path.exists():
        data = json.loads(auth_path.read_text())
        if "openrouter" in data:
            return data["openrouter"]["key"]
    return os.environ.get("OPENROUTER_API_KEY", "")


class OpenRouterClient:
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or _load_api_key()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Tonterias/HumaniaContract",
            "X-Title": "HumanIA Contract",
        })

    def chat_completion(
        self,
        messages: List[Dict],
        model: str = "deepseek/deepseek-v4-pro",
        temperature: float = 0.4,
        max_tokens: int = 800
    ) -> Dict:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for attempt in range(4):
            try:
                resp = self.session.post(
                    f"{self.BASE_URL}/chat/completions",
                    json=payload,
                    timeout=120
                )
                if resp.status_code == 429 and attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]["message"]
                result = {"content": choice.get("content", ""), "usage": data.get("usage", {})}
                if choice.get("reasoning_content"):
                    result["reasoning_content"] = choice["reasoning_content"]
                return result
            except requests.exceptions.Timeout:
                if attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
            except Exception as e:
                if attempt < 3 and getattr(resp, 'status_code', 500) >= 500:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
