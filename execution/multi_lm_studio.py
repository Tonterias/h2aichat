import requests
import time
from typing import Dict, List, Optional


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
        self.model_name = None

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

        self.model_name = model

        for attempt in range(self.max_retries):
            try:
                resp = self.session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    timeout=self.timeout
                )

                if resp.ok:
                    data = resp.json()
                    return {
                        "content": data['choices'][0]['message']['content'],
                        "model": data.get('model', model),
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


class MultiLMStudioClient:
    """Gestiona multiples instancias de LM Studio en diferentes puertos."""

    PORTS = {
        'gemma': 1234,
        'qwen': 1235,
        'default': 1234
    }

    MODEL_CONFIG = {
        'gemma': {
            'name': 'google/gemma-4-e4b',
            'port': 1234,
            'max_tokens': 512,
            'temperature': 0.3
        },
        'qwen': {
            'name': 'qwen2.5-coder-7b-instruct',
            'port': 1235,
            'max_tokens': 512,
            'temperature': 0.3
        }
    }

    def __init__(self):
        self.clients = {}

    def get_client(self, agent_id: str) -> LMStudioClient:
        """Obtiene o crea cliente para un agente especifico."""
        if agent_id not in self.clients:
            port = self.PORTS.get(agent_id, self.PORTS['default'])
            base_url = f"http://localhost:{port}/v1"
            self.clients[agent_id] = LMStudioClient(base_url=base_url)
        return self.clients[agent_id]

    def get_model_config(self, agent_id: str) -> Dict:
        """Retorna configuracion del modelo para un agente."""
        return self.MODEL_CONFIG.get(agent_id, {
            'name': 'local-model',
            'port': 1234,
            'max_tokens': 512,
            'temperature': 0.3
        })

    def chat_completion(
        self,
        agent_id: str,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = None,
        max_tokens: int = None
    ) -> Dict:
        """Enviar chat completion a traves del cliente del agente."""
        client = self.get_client(agent_id)
        config = self.get_model_config(agent_id)

        if model is None:
            model = config['name']
        if temperature is None:
            temperature = config['temperature']
        if max_tokens is None:
            max_tokens = config['max_tokens']

        return client.chat_completion(messages, model=model, temperature=temperature, max_tokens=max_tokens)

    def load_model(self, agent_id: str, model_name: str = None) -> bool:
        """Verifica si el modelo esta disponible."""
        client = self.get_client(agent_id)
        available = client.list_models()

        if model_name is None:
            config = self.get_model_config(agent_id)
            model_name = config['name']

        return model_name in available

    def health_check_all(self) -> Dict[str, bool]:
        """Verifica salud de todas las instancias."""
        health = {}
        for agent_id in self.clients:
            health[agent_id] = self.clients[agent_id].health_check()
        return health

    def get_active_model(self, agent_id: str) -> Optional[str]:
        """Retorna el modelo activo en la instancia del agente."""
        if agent_id in self.clients:
            return self.clients[agent_id].model_name
        return None