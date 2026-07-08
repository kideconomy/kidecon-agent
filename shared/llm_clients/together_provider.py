"""CANONICAL SOURCE: kidecon-hub/shared/llm_clients/
DO NOT EDIT in vendored copies — edit here and run sync.
"""
from __future__ import annotations

import json
import logging

from together import Together

from shared.llm_clients.base import BaseLLMProvider
from shared.llm_clients.base import LLMProviderError

logger = logging.getLogger(__name__)


class TogetherProvider(BaseLLMProvider):
    """LLM provider backed by the Together AI native SDK."""

    def __init__(self, api_key: str, **kwargs) -> None:
        self.client = Together(api_key=api_key)

    def complete(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.0,
        **kwargs,
    ) -> str:
        try:
            result = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
        except Exception as exc:
            msg = f"Together AI error: {exc}"
            logger.exception(msg)
            raise LLMProviderError(msg) from exc

        try:
            return result.choices[0].message.content
        except (IndexError, AttributeError) as exc:
            msg = "Together AI returned no choices"
            raise LLMProviderError(msg) from exc

    def complete_structured(
        self,
        messages: list[dict],
        model: str,
        response_schema: dict,
        temperature: float = 0.0,
    ) -> dict:
        try:
            result = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            msg = f"Together AI structured error: {exc}"
            logger.exception(msg)
            raise LLMProviderError(msg) from exc

        try:
            raw = result.choices[0].message.content
            return json.loads(raw)
        except (IndexError, AttributeError) as exc:
            msg = "Together AI returned no choices for structured request"
            raise LLMProviderError(msg) from exc
        except json.JSONDecodeError as exc:
            msg = f"Together AI returned invalid JSON: {exc}"
            raise LLMProviderError(msg) from exc
