import requests
import time
from typing import Optional, Dict, List


class LMStudioError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class LMStudioClient:
    def __init__(self, base_url: str = "http://localhost:1234/v1", timeout: int = 120, max_retries: int = 3):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def health_check(self) -> bool:
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            response = self.session.get(f"{self.base_url}/models", timeout=10)
            if response.ok:
                return [m['id'] for m in response.json().get('data', [])]
            return []
        except Exception:
            return []

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "local-model",
        temperature: float = 0.1,
        max_tokens: int = 512
    ) -> Dict:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        for attempt in range(self.max_retries):
            try:
                resp = self.session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    timeout=self.timeout
                )

                if resp.ok:
                    data = resp.json()
                    msg = data['choices'][0]['message']
                    return {
                        "content": msg.get('content', ''),
                        "reasoning_content": msg.get('reasoning_content', ''),
                        "model": data.get('model'),
                        "usage": data.get('usage', {})
                    }

                if resp.status_code == 500:
                    raise LMStudioError("INTERNAL_ERROR", "LM Studio internal error")
                elif resp.status_code == 503:
                    raise LMStudioError("SERVICE_UNAVAILABLE", "Model loading or unavailable")

                resp.raise_for_status()

            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                raise LMStudioError("CONNECTION_FAILED", str(e))
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise LMStudioError("UNEXPECTED", str(e))

        raise LMStudioError("MAX_RETRIES", "Exceeded maximum retry attempts")