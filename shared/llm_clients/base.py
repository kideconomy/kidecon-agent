"""CANONICAL SOURCE: kidecon-hub/shared/llm_clients/
DO NOT EDIT in vendored copies — edit here and run sync.
"""
import logging
from abc import ABC
from abc import abstractmethod

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Raised when an LLM provider returns an error or fails to respond."""


class BaseLLMProvider(ABC):
    """Abstract base for all LLM provider implementations.

    Every concrete provider must implement ``complete`` (plain text) and
    ``complete_structured`` (JSON conforming to a schema).
    """

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.0,
        **kwargs,
    ) -> str:
        """Return a plain-text completion string."""

    @abstractmethod
    def complete_structured(
        self,
        messages: list[dict],
        model: str,
        response_schema: dict,
        temperature: float = 0.0,
    ) -> dict:
        """Return a dict conforming to *response_schema*."""
