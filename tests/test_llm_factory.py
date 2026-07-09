"""Tests for shared.llm_clients — factory, providers, and tier router."""
import logging
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from shared.llm_clients.base import BaseLLMProvider
from shared.llm_clients.deepseek_provider import DeepSeekProvider
from shared.llm_clients.factory import LLMClientFactory
from shared.llm_clients.base import LLMProviderError
from shared.llm_clients.openrouter_provider import OpenRouterProvider
from shared.llm_clients.tiers import TierRouter
from shared.llm_clients.together_provider import TogetherProvider

logger = logging.getLogger(__name__)


# ── Factory tests ─────────────────────────────────────────────────────


class TestFactoryCreatesProviders:
    """LLMClientFactory.create returns the correct provider type."""

    @patch("shared.llm_clients.openrouter_provider.OpenRouter")
    def test_factory_creates_openrouter_provider(self, mock_sdk):
        provider = LLMClientFactory.create("openrouter", "sk-test")
        assert isinstance(provider, OpenRouterProvider)
        assert isinstance(provider, BaseLLMProvider)

    @patch("shared.llm_clients.together_provider.Together")
    def test_factory_creates_together_provider(self, mock_sdk):
        provider = LLMClientFactory.create("together", "sk-test")
        assert isinstance(provider, TogetherProvider)
        assert isinstance(provider, BaseLLMProvider)

    def test_factory_creates_deepseek_provider(self):
        provider = LLMClientFactory.create("deepseek", "sk-test")
        assert isinstance(provider, DeepSeekProvider)
        assert isinstance(provider, BaseLLMProvider)

    def test_factory_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider: nonexistent"):
            LLMClientFactory.create("nonexistent", "key")

    @patch("shared.llm_clients.openrouter_provider.OpenRouter")
    def test_factory_case_insensitive(self, mock_sdk):
        provider = LLMClientFactory.create("OpenRouter", "sk-test")
        assert isinstance(provider, OpenRouterProvider)


# ── TierRouter tests ──────────────────────────────────────────────────


class TestTierRouter:
    """TierRouter.resolve_tier maps messages to tier names."""

    def test_tier_code_prefix_routes_to_coding(self):
        msg = {"payload": {"text": "/code review this PR"}, "type": "chat"}
        assert TierRouter.resolve_tier(msg) == "coding"

    def test_tier_think_prefix_routes_to_strong(self):
        msg = {"payload": {"text": "/think deeply about architecture"}, "type": "chat"}
        assert TierRouter.resolve_tier(msg) == "strong"

    def test_tier_code_review_type_routes_to_coding(self):
        msg = {"payload": {"text": "normal text"}, "type": "code_review"}
        assert TierRouter.resolve_tier(msg) == "coding"

    def test_tier_default_is_daily(self):
        msg = {"payload": {"text": "hello world"}, "type": "chat"}
        assert TierRouter.resolve_tier(msg) == "daily"

    def test_tier_from_payload_text(self):
        msg = {"payload": {"text": "/code fix the bug"}}
        assert TierRouter.resolve_tier(msg) == "coding"

    def test_tier_missing_payload_defaults_daily(self):
        msg = {"type": "chat"}
        assert TierRouter.resolve_tier(msg) == "daily"

    def test_tier_empty_message_defaults_daily(self):
        assert TierRouter.resolve_tier({}) == "daily"

    def test_tier_code_review_type_overrides_text(self):
        """code_review type wins even if text doesn't start with /code."""
        msg = {"payload": {"text": "some analysis"}, "type": "code_review"}
        assert TierRouter.resolve_tier(msg) == "coding"


# ── OpenRouterProvider tests ──────────────────────────────────────────


class TestOpenRouterProvider:
    """OpenRouterProvider delegates to the native SDK."""

    @patch("shared.llm_clients.openrouter_provider.OpenRouter")
    def test_complete_returns_content(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        # Build a response that mimics ChatResult.choices[0].message.content
        mock_message = MagicMock()
        mock_message.content = "Hello from LLM"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_result = MagicMock()
        mock_result.choices = [mock_choice]
        mock_client.chat.send.return_value = mock_result

        provider = OpenRouterProvider(api_key="sk-test")
        text = provider.complete(
            messages=[{"role": "user", "content": "hi"}],
            model="openai/gpt-4o",
        )
        assert text == "Hello from LLM"
        mock_client.chat.send.assert_called_once()

    @patch("shared.llm_clients.openrouter_provider.OpenRouter")
    def test_complete_structured_returns_dict(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        mock_message = MagicMock()
        mock_message.content = '{"answer": 42}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_result = MagicMock()
        mock_result.choices = [mock_choice]
        mock_client.chat.send.return_value = mock_result

        provider = OpenRouterProvider(api_key="sk-test")
        result = provider.complete_structured(
            messages=[{"role": "user", "content": "give me json"}],
            model="openai/gpt-4o",
            response_schema={"name": "test", "schema": {"type": "object"}},
        )
        assert result == {"answer": 42}

    @patch("shared.llm_clients.openrouter_provider.OpenRouter")
    def test_complete_sdk_error_raises_provider_error(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.send.side_effect = RuntimeError("API down")

        provider = OpenRouterProvider(api_key="sk-test")
        with pytest.raises(LLMProviderError, match="OpenRouter error"):
            provider.complete(messages=[], model="test")

    @patch("shared.llm_clients.openrouter_provider.OpenRouter")
    def test_complete_no_choices_raises(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_result = MagicMock()
        mock_result.choices = []
        mock_client.chat.send.return_value = mock_result

        provider = OpenRouterProvider(api_key="sk-test")
        with pytest.raises(LLMProviderError, match="no choices"):
            provider.complete(messages=[], model="test")


# ── TogetherProvider tests ────────────────────────────────────────────


class TestTogetherProvider:
    """TogetherProvider delegates to the Together SDK."""

    @patch("shared.llm_clients.together_provider.Together")
    def test_complete_returns_content(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        mock_message = MagicMock()
        mock_message.content = "Together response"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_result = MagicMock()
        mock_result.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_result

        provider = TogetherProvider(api_key="sk-test")
        text = provider.complete(
            messages=[{"role": "user", "content": "hi"}],
            model="meta-llama/Llama-3-70b",
        )
        assert text == "Together response"

    @patch("shared.llm_clients.together_provider.Together")
    def test_complete_structured_returns_dict(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        mock_message = MagicMock()
        mock_message.content = '{"status": "ok"}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_result = MagicMock()
        mock_result.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_result

        provider = TogetherProvider(api_key="sk-test")
        result = provider.complete_structured(
            messages=[{"role": "user", "content": "json please"}],
            model="meta-llama/Llama-3-70b",
            response_schema={"type": "object"},
        )
        assert result == {"status": "ok"}

    @patch("shared.llm_clients.together_provider.Together")
    def test_complete_sdk_error_raises_provider_error(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("fail")

        provider = TogetherProvider(api_key="sk-test")
        with pytest.raises(LLMProviderError, match="Together AI error"):
            provider.complete(messages=[], model="test")


# ── DeepSeekProvider tests ────────────────────────────────────────────


class TestDeepSeekProvider:
    """DeepSeekProvider uses raw httpx to DeepSeek's API."""

    @patch("shared.llm_clients.deepseek_provider.httpx.post")
    def test_complete_returns_content(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "DeepSeek says hi"}}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        provider = DeepSeekProvider(api_key="sk-test")
        text = provider.complete(
            messages=[{"role": "user", "content": "hello"}],
            model="deepseek-chat",
        )
        assert text == "DeepSeek says hi"
        mock_post.assert_called_once()

        # Verify auth header
        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test"

    @patch("shared.llm_clients.deepseek_provider.httpx.post")
    def test_complete_structured_returns_dict(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"value": 1}'}}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        provider = DeepSeekProvider(api_key="sk-test")
        result = provider.complete_structured(
            messages=[{"role": "user", "content": "json"}],
            model="deepseek-chat",
            response_schema={"type": "object"},
        )
        assert result == {"value": 1}

        # Verify response_format was passed
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["response_format"] == {"type": "json_object"}

    @patch("shared.llm_clients.deepseek_provider.httpx.post")
    def test_complete_http_error_raises_provider_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=mock_resp,
        )
        mock_post.return_value = mock_resp

        provider = DeepSeekProvider(api_key="sk-test")
        with pytest.raises(LLMProviderError, match="DeepSeek HTTP 500"):
            provider.complete(messages=[], model="deepseek-chat")

    def test_custom_base_url(self):
        provider = DeepSeekProvider(api_key="sk-test", base_url="https://custom.api.com/v2/")
        assert provider.base_url == "https://custom.api.com/v2"
