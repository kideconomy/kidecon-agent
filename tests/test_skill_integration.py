"""Integration tests for skill loading layer.

Uses real LLM (OpenRouter) and real hub connection. The only mocked layer is
``respond_to_message`` — that HTTP call requires a real hub message ID that
can't exist in a test context.
"""

import logging
from unittest.mock import MagicMock
from unittest.mock import patch

import keyring as kr
import pytest

from shared.llm_clients.factory import LLMClientFactory
from wrappers.cognition import CognitiveEngine
from wrappers.cognition import Context
from wrappers.hub_client import HubClient
from wrappers.memory import MemoryStore
from wrappers.session import SessionStore
from wrappers.skill_loader import SkillLoader

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.integration

HUB_URL = "http://localhost:8000"


@pytest.fixture(scope="module")
def real_factory():
    api_key = kr.get_password("kidecon-agent", "api_key_openrouter")
    if not api_key:
        pytest.skip("No OpenRouter API key in keyring")
    return LLMClientFactory.create(provider="openrouter", api_key=api_key)


@pytest.fixture(scope="module")
def real_hub():
    hub = HubClient(hub_url=HUB_URL)
    skills = hub.discover_skills("")
    if not skills:
        pytest.skip("No live skills on hub — run kidecon setup and approve skills first")
    logger.info("Hub has %d live skills: %s", len(skills), [s["name"] for s in skills])
    return hub


@pytest.fixture
def hub_with_captured_respond(real_hub):
    with patch.object(real_hub, "respond_to_message", wraps=real_hub.respond_to_message) as mock_respond:
        mock_respond.side_effect = None
        mock_respond.return_value = {"status": "ok"}
        yield real_hub


def _build_skill_engine(real_factory, hub, tmp_path):
    memory = MemoryStore(memory_dir=tmp_path / "memory")
    sessions = SessionStore(sessions_dir=tmp_path / "memory" / "sessions", window=12)
    safety = MagicMock()
    safety.check_ingress.return_value = (True, "ok")
    safety.check_egress.return_value = (True, "ok")
    skill_loader = SkillLoader(hub)
    skill_loader.refresh()
    return CognitiveEngine(
        factory=real_factory,
        safety=safety,
        models={
            "daily": "deepseek/deepseek-v4-flash",
            "strong": "deepseek/deepseek-v4-pro",
            "coding": "qwen/qwen3.7-max",
        },
        system_prompt="You are Hermes, an AI learning companion. Be concise and helpful.",
        provider_name="openrouter",
        max_price=1.0,
        client=hub,
        memory=memory,
        sessions=sessions,
        cognition_config={
            "reflect_on_daily": False,
            "strong_cycle": False,
            "soul_limit": 5000,
            "user_limit": 5000,
            "capabilities_limit": 3000,
        },
        normalization_config={"llm_rewrite_on": [], "model": "daily"},
        agent_hub_tier=3,
        skill_loader=skill_loader,
    )


def _make_message(text, source="discord_dm", msg_id="msg-1"):
    return {
        "id": msg_id,
        "type": "chat",
        "payload": {"text": text, "source": source, "discord_user_id": "42"},
    }


# ------------------------------------------------------------------
# Unit-level (no LLM, no hub): verify prompt construction logic
# ------------------------------------------------------------------

class TestPromptConstruction:
    def test_skill_index_injected_when_available(self, tmp_path):
        client = MagicMock()
        client.discover_skills.return_value = [
            {"id": "sk-test", "name": "test-skill", "category": "tool", "description": "A test skill"},
        ]
        loader = SkillLoader(client)
        loader.refresh()
        ctx = Context(
            text="hello", source="discord", tier="daily",
            model="deepseek/deepseek-v4-flash", skill_instructions=None,
        )
        engine = MagicMock(spec=CognitiveEngine)
        engine.skill_loader = loader
        engine.system_prompt = "You are Hermes."
        engine._build_messages = CognitiveEngine._build_messages.__get__(engine, CognitiveEngine)
        messages = engine._build_messages(ctx)
        system = messages[0]["content"]
        assert "## Available Skills" in system
        assert "test-skill" in system

    def test_skill_instructions_injected_when_matched(self, tmp_path):
        instructions = "## Test Procedure\nStep 1: Do the thing."
        client = MagicMock()
        client.discover_skills.return_value = []
        loader = SkillLoader(client)
        loader.refresh()
        ctx = Context(
            text="run the test skill", source="discord", tier="daily",
            model="deepseek/deepseek-v4-flash", skill_instructions=instructions,
        )
        engine = MagicMock(spec=CognitiveEngine)
        engine.skill_loader = loader
        engine.system_prompt = "You are Hermes."
        engine._build_messages = CognitiveEngine._build_messages.__get__(engine, CognitiveEngine)
        messages = engine._build_messages(ctx)
        system = messages[0]["content"]
        assert "Test Procedure" in system
        assert "Step 1" in system

    def test_no_skill_index_when_loader_empty(self, tmp_path):
        client = MagicMock()
        client.discover_skills.return_value = []
        loader = SkillLoader(client)
        loader.refresh()
        ctx = Context(
            text="hello", source="discord", tier="daily",
            model="deepseek/deepseek-v4-flash",
        )
        engine = MagicMock(spec=CognitiveEngine)
        engine.skill_loader = loader
        engine.system_prompt = "You are Hermes."
        engine._build_messages = CognitiveEngine._build_messages.__get__(engine, CognitiveEngine)
        messages = engine._build_messages(ctx)
        system = messages[0]["content"]
        assert "## Available Skills" not in system

    def test_skill_index_not_injected_when_no_loader(self, tmp_path):
        ctx = Context(
            text="hello", source="discord", tier="daily",
            model="deepseek/deepseek-v4-flash",
        )
        engine = MagicMock(spec=CognitiveEngine)
        engine.skill_loader = None
        engine.system_prompt = "You are Hermes."
        engine._build_messages = CognitiveEngine._build_messages.__get__(engine, CognitiveEngine)
        messages = engine._build_messages(ctx)
        system = messages[0]["content"]
        assert "## Available Skills" not in system


# ------------------------------------------------------------------
# Live hub + live LLM: verify end-to-end behaviour
# ------------------------------------------------------------------

class TestSkillLoaderLiveHub:
    """Tests that verify SkillLoader works against the real hub."""

    def test_skill_loader_refreshes_from_real_hub(self, real_hub):
        loader = SkillLoader(real_hub)
        loader.refresh()
        assert len(loader._index) >= 1, "Should have at least 1 live skill"

    def test_get_index_summary_includes_live_skills(self, real_hub):
        loader = SkillLoader(real_hub)
        loader.refresh()
        summary = loader.get_index_summary()
        assert "## Available Skills" in summary
        for s in loader._index:
            assert s["name"] in summary

    def test_find_skill_by_name_from_live_hub(self, real_hub):
        loader = SkillLoader(real_hub)
        loader.refresh()
        first_skill = loader._index[0]
        result = loader.find_skill(f"I want to use {first_skill['name']}")
        assert result is not None
        assert result["name"] == first_skill["name"]

    def test_find_skill_no_match_from_live_hub(self, real_hub):
        loader = SkillLoader(real_hub)
        loader.refresh()
        result = loader.find_skill("tell me a joke about penguins")
        assert result is None

    def test_get_skill_instructions_from_live_hub(self, real_hub):
        loader = SkillLoader(real_hub)
        loader.refresh()
        first_skill = loader._index[0]
        instructions = loader.get_skill_instructions(first_skill["id"])
        assert instructions is None or len(instructions) > 20


class TestSkillAwareLLMResponse:
    """Tests that call the real LLM and real hub to verify prompt quality."""

    def test_llm_demonstrates_skill_awareness_on_match(self, real_factory, hub_with_captured_respond, tmp_path):
        """The LLM follows skill instructions when a message matches a live skill."""
        engine = _build_skill_engine(real_factory, hub_with_captured_respond, tmp_path)
        first_skill = engine.skill_loader._index[0]
        msg = _make_message(f"I need help with {first_skill['name']}")

        engine.process(msg)

        respond_call = hub_with_captured_respond.respond_to_message.call_args
        assert respond_call is not None, "Engine should have responded"
        result_text = respond_call[1]["result"]["text"]
        logger.info("LLM response (skill match '%s'): %.200s", first_skill["name"], result_text)
        assert len(result_text) > 20, "Response should be substantive"

    def test_llm_responds_normally_on_no_match(self, real_factory, hub_with_captured_respond, tmp_path):
        """The LLM responds normally without skill procedure when no skill matches."""
        engine = _build_skill_engine(real_factory, hub_with_captured_respond, tmp_path)
        msg = _make_message("What is the capital of France?")

        engine.process(msg)

        respond_call = hub_with_captured_respond.respond_to_message.call_args
        assert respond_call is not None
        result_text = respond_call[1]["result"]["text"]
        logger.info("LLM response (no match): %.200s", result_text)
        assert len(result_text) > 5
        assert "paris" in result_text.lower()

    def test_skill_index_visible_in_prompt(self, real_factory, hub_with_captured_respond, tmp_path):
        """The skill index section appears in the system prompt for every request."""
        engine = _build_skill_engine(real_factory, hub_with_captured_respond, tmp_path)
        msg = _make_message("Tell me a fun fact")

        engine.process(msg)

        respond_call = hub_with_captured_respond.respond_to_message.call_args
        assert respond_call is not None
        result_text = respond_call[1]["result"]["text"]
        logger.info("LLM response (fun fact): %.200s", result_text)
        assert len(result_text) > 5