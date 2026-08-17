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
        for provider in ["opencode-go", "opencode"]:
            if provider in data:
                return data[provider]["key"]
    return os.environ.get("OPENCODE_API_KEY", "")


class OpenCodeGoClient:
    BASE_URL = "https://opencode.ai/zen/go/v1"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or _load_api_key()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 400,
        reasoning_effort: str = None
    ) -> Dict:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        # FASE: bajar/quitar el razonamiento (p. ej. Kimi gastaba sus tokens razonando
        # y devolvia vacio). 'none' -> responde directo, mas rapido y sin vaciarse.
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        last_error = None
        for attempt in range(4):
            resp = self.session.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload,
                timeout=120
            )
            if resp.status_code == 429 and attempt < 3:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
                last_error = f"429 retry {attempt + 1}/3 after {wait}s"
                continue
            # EL PROVEEDOR RETIRA UN PARAMETRO SIN AVISAR. Algunos modelos dejan de aceptar el
            # campo `reasoning` y devuelven 400 «Extra inputs are not permitted, field:
            # 'reasoning'» — y con el, ese bot se queda MUDO en la mesa. En vez de que un cambio
            # del proveedor calle un asiento, si el 400 es por ese campo se reintenta SIN el.
            if (resp.status_code == 400 and "reasoning" in payload
                    and "reasoning" in (resp.text or "").lower() and attempt < 3):
                payload.pop("reasoning", None)
                last_error = "400: el modelo no acepta 'reasoning'; reintento sin el"
                continue
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            return {
                "content": msg.get("content", ""),
                "reasoning_content": msg.get("reasoning_content", ""),
                "model": data.get("model"),
                "usage": data.get("usage", {})
            }
        raise requests.HTTPError(last_error or "429 Too Many Requests after 3 retries", response=resp)
