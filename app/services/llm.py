import json
from typing import Any

import httpx

from app.core.config import Settings


class LLMError(RuntimeError):
    """Raised when the model call fails."""


class MissingApiKeyError(LLMError):
    """Raised when no model API key is configured."""


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.settings.zhipu_api_key:
            raise MissingApiKeyError(
                "ZHIPU_API_KEY is not configured. Set it in the environment or .env/config.py."
            )

        payload = {
            "model": self.settings.zhipu_chat_model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.zhipu_api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for _ in range(self.settings.llm_max_retries + 1):
            try:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    response = client.post(self._chat_url(), headers=headers, json=payload)
                    response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return json.loads(_extract_json(content))
            except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
                last_error = exc

        raise LLMError(f"LLM request failed: {last_error}") from last_error

    def _chat_url(self) -> str:
        base_url = self.settings.zhipu_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"


def _extract_json(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]

