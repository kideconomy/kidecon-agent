"""CANONICAL SOURCE: kidecon-hub/shared/llm_clients/
DO NOT EDIT in vendored copies — edit here and run sync.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shared.llm_clients.deepseek_provider import DeepSeekProvider
from shared.llm_clients.openrouter_provider import OpenRouterProvider
from shared.llm_clients.together_provider import TogetherProvider

if TYPE_CHECKING:
    from shared.llm_clients.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class LLMClientFactory:
    """Create an LLM provider by name.

    Usage::

        provider = LLMClientFactory.create("openrouter", api_key="sk-...")
        text = provider.complete(messages=[...], model="openai/gpt-4o")
    """

    PROVIDERS: dict[str, type[BaseLLMProvider]] = {
        "openrouter": OpenRouterProvider,
        "together": TogetherProvider,
        "deepseek": DeepSeekProvider,
    }

    @staticmethod
    def create(provider: str, api_key: str, **kwargs) -> BaseLLMProvider:
        """Return a ``BaseLLMProvider`` for *provider*.

        Raises ``ValueError`` when *provider* is not recognised.
        """
        cls = LLMClientFactory.PROVIDERS.get(provider.lower())
        if not cls:
            supported = list(LLMClientFactory.PROVIDERS.keys())
            msg = f"Unsupported provider: {provider}. Supported: {supported}"
            raise ValueError(msg)
        return cls(api_key=api_key, **kwargs)
