"""Tests for the lexor_call cognition-loop integration.

Covers: PLAN schema includes lexor_call, _dispatch_step routes lexor_call to
LexorClient, results are PII-scrubbed before entering the trace, egress runs
on lexor-bearing turns regardless of source, system prompt tail includes the
Lexor instructions only when the client is present, and Lexor-disabled
(client=None) is a no-op with zero behavior change.
"""

import logging
from unittest.mock import MagicMock

from wrappers.cognition import PLAN_SCHEMA
from wrappers.cognition import CognitiveEngine
from wrappers.cognition import Context
from wrappers.cognition import Step
from wrappers.cognition import _compact_str
from wrappers.cognition import _load_lexor_instructions
from wrappers.memory import MemoryStore
from wrappers.session import SessionStore

logger = logging.getLogger(__name__)


def _make_factory(structured_responses=None, complete_responses=None):
    factory = MagicMock()
    factory.complete.return_value = "Default response."
    if complete_responses:
        factory.complete.side_effect = complete_responses
    if structured_responses:
        factory.complete_structured.side_effect = structured_responses
    else:
        factory.complete_structured.return_value = {
            "intent": "question",
            "complexity": "simple",
            "emotion": "neutral",
            "needs_tool": False,
            "needs_memory": False,
            "suggested_tier": "daily",
        }
    return factory


def _build_engine(
    tmp_path,
    factory=None,
    client=None,
    *,
    agent_hub_tier=3,
    lexor_client=None,
    safety=None,
):
    memory = MemoryStore(memory_dir=tmp_path / "kidecon" / "memory")
    sessions = SessionStore(sessions_dir=tmp_path / "kidecon" / "memory" / "sessions", window=12)
    factory = factory or _make_factory()
    client = client or MagicMock()
    client.push_lesson.return_value = {"lesson_id": "les-1", "status": "queued"}
    if safety is None:
        safety = MagicMock()
        safety.check_ingress.return_value = (True, "ok")
        safety.check_egress.return_value = (True, "ok")
    return CognitiveEngine(
        factory=factory,
        safety=safety,
        models={"daily": "m/d", "strong": "m/s", "coding": "m/c"},
        system_prompt="You are Hermes.",
        provider_name="openrouter",
        max_price=0.01,
        client=client,
        memory=memory,
        sessions=sessions,
        cognition_config={"reflect_on_daily": False, "soul_limit": 5000, "user_limit": 5000, "capabilities_limit": 3000},
        normalization_config={"llm_rewrite_on": [], "model": "daily"},
        agent_hub_tier=agent_hub_tier,
        lexor_client=lexor_client,
    )


# ------------------------------------------------------------------
# PLAN schema includes lexor_call
# ------------------------------------------------------------------
def test_plan_schema_action_enum_includes_lexor_call():
    actions = PLAN_SCHEMA["schema"]["properties"]["steps"]["items"]["properties"]["action"]["enum"]
    assert "lexor_call" in actions
    assert "hub_call" in actions
    assert "llm" in actions


# ------------------------------------------------------------------
# _dispatch_step routes lexor_call to LexorClient
# ------------------------------------------------------------------
def test_dispatch_lexor_call_invokes_client_and_returns_result(tmp_path):
    fake_client = MagicMock()
    fake_client.call.return_value = {"result": {"blueprints": ["pbc"]}, "error": None}
    engine = _build_engine(tmp_path, lexor_client=fake_client)


    output = engine._dispatch_step(
        Step(action="lexor_call", params={"tool": "blueprint.list", "params": {}}),
        messages=[],
        context=MagicMock(),
    )
    fake_client.call.assert_called_once_with("blueprint.list", {}, 3)
    assert "pbc" in output
    assert "blueprints" in output


def test_dispatch_lexor_call_returns_error_message_when_client_errors(tmp_path):
    fake_client = MagicMock()
    fake_client.call.return_value = {
        "result": None,
        "error": "Lexor lookup failed. Reason: token expired. To proceed: re-issue.",
    }
    engine = _build_engine(tmp_path, lexor_client=fake_client)


    output = engine._dispatch_step(
        Step(action="lexor_call", params={"tool": "blueprint.list", "params": {}}),
        messages=[],
        context=MagicMock(),
    )
    assert "token expired" in output
    fake_client.call.assert_called_once()


def test_dispatch_lexor_call_passes_agent_hub_tier(tmp_path):
    fake_client = MagicMock()
    fake_client.call.return_value = {"result": {"ok": True}, "error": None}
    engine = _build_engine(tmp_path, agent_hub_tier=2, lexor_client=fake_client)


    engine._dispatch_step(
        Step(action="lexor_call", params={"tool": "blueprint.list", "params": {}}),
        messages=[],
        context=MagicMock(),
    )
    args, kwargs = fake_client.call.call_args
    assert args[2] == 2 or kwargs.get("agent_hub_tier") == 2


# ------------------------------------------------------------------
# PII scrubbing before entering trace
# ------------------------------------------------------------------
def test_lexor_result_is_scrubbed_before_entering_output(tmp_path):
    fake_client = MagicMock()
    fake_client.call.return_value = {
        "result": {
            "contact": "reach me at leaker@example.com or 555-123-4567",
            "uuid_ref": "12345678-1234-1234-1234-123456789012",
            "data": "kept",
        },
        "error": None,
    }
    engine = _build_engine(tmp_path, lexor_client=fake_client)


    output = engine._dispatch_step(
        Step(action="lexor_call", params={"tool": "entity.get", "params": {"slug": "x"}}),
        messages=[],
        context=MagicMock(),
    )
    assert "leaker@example.com" not in output
    assert "555-123-4567" not in output
    assert "[REDACTED]" in output
    assert "kept" in output
    assert "12345678-1234-1234-1234-123456789012" not in output


# ------------------------------------------------------------------
# Lexor disabled (client=None) is a no-op
# ------------------------------------------------------------------
def test_lexor_call_is_noop_when_client_is_none(tmp_path):
    engine = _build_engine(tmp_path, lexor_client=None)

    output = engine._dispatch_step(
        Step(action="lexor_call", params={"tool": "blueprint.list", "params": {}}),
        messages=[],
        context=MagicMock(),
    )
    assert output == ""


def test_engine_constructs_without_lexor_client_kwarg(tmp_path):
    """Backward compat: callers that don't pass lexor_client get None."""
    memory = MemoryStore(memory_dir=tmp_path / "mem")
    sessions = SessionStore(sessions_dir=tmp_path / "sess", window=12)
    engine = CognitiveEngine(
        factory=MagicMock(),
        safety=MagicMock(),
        models={},
        system_prompt="x",
        provider_name="openrouter",
        max_price=0.01,
        client=MagicMock(),
        memory=memory,
        sessions=sessions,
    )
    assert engine.lexor_client is None


# ------------------------------------------------------------------
# Egress runs on lexor-bearing turns for non-Discord sources
# ------------------------------------------------------------------
def test_check_egress_runs_for_lexor_turn_non_discord_source(tmp_path):
    safety = MagicMock()
    safety.check_ingress.return_value = (True, "ok")
    safety.check_egress.return_value = (True, "ok")
    engine = _build_engine(tmp_path, lexor_client=MagicMock(), safety=safety)
    # a2a source normally skips egress, but used_lexor=True forces it
    passed, _ = engine._check_egress("a2a", "some result", "msg-1", used_lexor=True)
    assert passed is True
    safety.check_egress.assert_called_once()


def test_check_egress_blocks_on_lexor_turn_non_discord_source(tmp_path):
    safety = MagicMock()
    safety.check_ingress.return_value = (True, "ok")
    safety.check_egress.return_value = (False, "blocked-reason")
    engine = _build_engine(tmp_path, lexor_client=MagicMock(), safety=safety)
    original = "ORIGINAL_SENSITIVE_RESULT_TEXT"
    passed, result = engine._check_egress("a2a", original, "msg-1", used_lexor=True)
    assert passed is False
    # The original sensitive result must NOT pass through to the user.
    assert original not in result


def test_check_egress_skips_when_not_discord_and_no_lexor(tmp_path):
    safety = MagicMock()
    safety.check_ingress.return_value = (True, "ok")
    safety.check_egress.return_value = (True, "ok")
    engine = _build_engine(tmp_path, lexor_client=None, safety=safety)
    engine._check_egress("a2a", "result", "msg-1", used_lexor=False)
    safety.check_egress.assert_not_called()


# ------------------------------------------------------------------
# System prompt tail includes Lexor instructions only when client present
# ------------------------------------------------------------------
def test_lexor_instructions_present_when_client_set(tmp_path):
    fake_client = MagicMock()
    fake_client.min_hub_tier = 3
    engine = _build_engine(tmp_path, agent_hub_tier=3, lexor_client=fake_client)

    ctx = Context(text="hi", source="discord", tier="daily", model="m/d")
    messages = engine._build_messages(ctx)
    system_content = messages[0]["content"]
    assert "Lexor" in system_content
    assert "blueprint.list" in system_content
    assert "informational" in system_content.lower()


def test_lexor_instructions_absent_when_client_none(tmp_path):
    engine = _build_engine(tmp_path, lexor_client=None)

    ctx = Context(text="hi", source="discord", tier="daily", model="m/d")
    messages = engine._build_messages(ctx)
    system_content = messages[0]["content"]
    assert "Lexor" not in system_content


def test_lexor_instructions_absent_when_tier_below_min(tmp_path):
    """Non-staff agents with a provisioned client must NOT see the Lexor block.

    Prevents leaking the staff-only tool inventory to a tier-1 agent that
    happens to have api_key_lexor in the keyring.
    """
    fake_client = MagicMock()
    fake_client.min_hub_tier = 3
    engine = _build_engine(tmp_path, agent_hub_tier=1, lexor_client=fake_client)

    ctx = Context(text="hi", source="discord", tier="daily", model="m/d")
    messages = engine._build_messages(ctx)
    system_content = messages[0]["content"]
    assert "Lexor" not in system_content


def test_build_messages_includes_lexor_block_when_client_set(tmp_path):
    fake_client = MagicMock()
    fake_client.min_hub_tier = 3
    engine = _build_engine(tmp_path, agent_hub_tier=3, lexor_client=fake_client)

    ctx = Context(text="hi", source="discord", tier="daily", model="m/d")
    messages = engine._build_messages(ctx)
    system_content = messages[0]["content"]
    assert "Lexor" in system_content
    assert "blueprint.list" in system_content


def test_build_messages_omits_lexor_block_when_client_none(tmp_path):
    engine = _build_engine(tmp_path, lexor_client=None)

    ctx = Context(text="hi", source="discord", tier="daily", model="m/d")
    messages = engine._build_messages(ctx)
    system_content = messages[0]["content"]
    assert "Lexor" not in system_content


# ------------------------------------------------------------------
# _compact_str helper
# ------------------------------------------------------------------
def test_compact_str_dict_returns_json():
    assert '"key": "value"' in _compact_str({"key": "value"})


def test_compact_str_string_passthrough():
    assert _compact_str("already a string") == "already a string"


def test_load_lexor_instructions_returns_content():
    content = _load_lexor_instructions()
    assert content is not None
    assert "Lexor" in content
    assert "blueprint.list" in content


# ------------------------------------------------------------------
# End-to-end: process() with a lexor_call plan step
# ------------------------------------------------------------------
def test_process_with_lexor_call_step_runs_and_egresses(tmp_path):
    """Full process() turn where the planner emits a lexor_call step.

    Verifies the lexor client is invoked mid-turn, the result flows into the
    final response, and egress runs on the lexor-bearing turn.
    """
    fake_lexor = MagicMock()
    fake_lexor.min_hub_tier = 3
    fake_lexor.call.return_value = {
        "result": {"blueprints": [{"id": "de_pbc_formation", "name": "Delaware PBC"}]},
        "error": None,
    }
    # Planner returns a lexor_call step, then an llm step.
    plan_response = {
        "steps": [
            {
                "action": "lexor_call",
                "params": {"tool": "blueprint.list", "params": {}},
                "rationale": "user asked about entity formation",
            },
            {
                "action": "llm",
                "params": {"model": "m/s"},
                "rationale": "answer from retrieved context",
            },
        ],
    }
    factory = _make_factory(
        structured_responses=[
            {  # CLASSIFY (orient)
                "intent": "question",
                "complexity": "moderate",
                "emotion": "neutral",
                "needs_tool": True,
                "needs_memory": False,
                "suggested_tier": "strong",
            },
            plan_response,  # PLAN
            {  # REFLECT
                "quality": 0.8,
                "critique": "ok",
                "keep": [],
                "self_edit": None,
                "lesson": None,
            },
        ],
        complete_responses=["A Delaware PBC requires formation documents."],
    )
    safety = MagicMock()
    safety.check_ingress.return_value = (True, "ok")
    safety.check_egress.return_value = (True, "ok")
    engine = _build_engine(
        tmp_path,
        factory=factory,
        agent_hub_tier=3,
        lexor_client=fake_lexor,
        safety=safety,
    )

    message = {
        "id": "msg-lexor-1",
        "type": "chat",
        # /think prefix triggers the strong/full cognition path so the PLAN
        # step (which emits lexor_call) actually runs.
        "payload": {
            "text": "/think What does a Delaware PBC require?",
            "source": "discord",
            "discord_user_id": "42",
        },
    }
    engine.process(message)
    fake_lexor.call.assert_called_once()
    # egress must have been invoked (lexor-bearing turn)
    safety.check_egress.assert_called_once()
    engine.client.respond_to_message.assert_called_once()
    sent_result = engine.client.respond_to_message.call_args.kwargs["result"]["text"]
    assert "Delaware PBC" in sent_result
