"""CANONICAL SOURCE: kidecon-hub/shared/llm_clients/
DO NOT EDIT in vendored copies — edit here and run sync.
"""
from __future__ import annotations

import json
import logging

from openrouter import OpenRouter
from openrouter.components.chatformatjsonschemaconfig import ChatFormatJSONSchemaConfig
from openrouter.components.chatjsonschemaconfig import ChatJSONSchemaConfig
from openrouter.components.providerpreferences import ProviderPreferences

from shared.llm_clients.base import BaseLLMProvider
from shared.llm_clients.base import LLMProviderError

logger = logging.getLogger(__name__)


class OpenRouterProvider(BaseLLMProvider):
    """LLM provider backed by the OpenRouter native SDK.

    Supports ``max_price`` via the ``provider`` kwarg forwarded to
    ``chat.send(provider=ProviderPreferences(max_price=...))``.
    """

    def __init__(self, api_key: str, **kwargs) -> None:
        self.client = OpenRouter(api_key=api_key)

    def complete(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.0,
        **kwargs,
    ) -> str:
        send_kwargs: dict = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
        }
        # Forward provider preferences (e.g. max_price for tier cost caps).
        if "provider" in kwargs:
            provider_raw = kwargs["provider"]
            if isinstance(provider_raw, dict):
                send_kwargs["provider"] = ProviderPreferences(**provider_raw)
            else:
                send_kwargs["provider"] = provider_raw

        try:
            result = self.client.chat.send(**send_kwargs)
        except Exception as exc:
            msg = f"OpenRouter error: {exc}"
            logger.exception(msg)
            raise LLMProviderError(msg) from exc

        try:
            return result.choices[0].message.content
        except (IndexError, AttributeError) as exc:
            msg = "OpenRouter returned no choices"
            raise LLMProviderError(msg) from exc

    def complete_structured(
        self,
        messages: list[dict],
        model: str,
        response_schema: dict,
        temperature: float = 0.0,
    ) -> dict:
        schema_name = response_schema.get("name", "response")
        schema_body = response_schema.get("schema", response_schema)

        response_format = ChatFormatJSONSchemaConfig(
            type="json_schema",
            json_schema=ChatJSONSchemaConfig(
                name=schema_name,
                schema_=schema_body,
                strict=True,
            ),
        )

        try:
            result = self.client.chat.send(
                messages=messages,
                model=model,
                temperature=temperature,
                response_format=response_format,
            )
        except Exception as exc:
            msg = f"OpenRouter structured error: {exc}"
            logger.exception(msg)
            raise LLMProviderError(msg) from exc

        try:
            raw = result.choices[0].message.content
            return json.loads(raw)
        except (IndexError, AttributeError) as exc:
            msg = "OpenRouter returned no choices for structured request"
            raise LLMProviderError(msg) from exc
        except json.JSONDecodeError as exc:
            msg = f"OpenRouter returned invalid JSON: {exc}"
            raise LLMProviderError(msg) from exc
