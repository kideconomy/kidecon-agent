"""CANONICAL SOURCE: kidecon-hub/shared/llm_clients/
DO NOT EDIT in vendored copies — edit here and run sync.
"""
from __future__ import annotations

import json
import logging

import httpx

from shared.llm_clients.base import BaseLLMProvider
from shared.llm_clients.base import LLMProviderError

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_CHAT_COMPLETIONS_PATH = "/chat/completions"
_TIMEOUT = 60


class DeepSeekProvider(BaseLLMProvider):
    """LLM provider calling the DeepSeek OpenAI-compatible API via httpx.

    Uses raw ``httpx`` — no OpenAI SDK.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        **kwargs,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    # ── internal ──────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, payload: dict) -> dict:
        url = f"{self.base_url}{_CHAT_COMPLETIONS_PATH}"
        try:
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=_TIMEOUT)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            msg = f"DeepSeek HTTP {exc.response.status_code}: {exc.response.text}"
            logger.exception(msg)
            raise LLMProviderError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"DeepSeek request error: {exc}"
            logger.exception(msg)
            raise LLMProviderError(msg) from exc
        return resp.json()

    # ── public API ────────────────────────────────────────────────────

    def complete(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.0,
        **kwargs,
    ) -> str:
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        data = self._post(payload)

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            msg = "DeepSeek returned no choices"
            raise LLMProviderError(msg) from exc

    def complete_structured(
        self,
        messages: list[dict],
        model: str,
        response_schema: dict,
        temperature: float = 0.0,
    ) -> dict:
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        data = self._post(payload)

        try:
            raw = data["choices"][0]["message"]["content"]
            return json.loads(raw)
        except (KeyError, IndexError) as exc:
            msg = "DeepSeek returned no choices for structured request"
            raise LLMProviderError(msg) from exc
        except json.JSONDecodeError as exc:
            msg = f"DeepSeek returned invalid JSON: {exc}"
            raise LLMProviderError(msg) from exc
