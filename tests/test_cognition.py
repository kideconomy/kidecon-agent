"""C1 + C2 cognitive architecture tests.

Covers the 7 required C2 tests plus C1 daily-parity and restart-survival
behavior. All tests isolate HOME (see conftest.py) so memory files land in a
tmp dir. LLM and hub calls are mocked — no network.
"""

import logging
from unittest.mock import MagicMock

import pytest

from wrappers.cognition import CognitiveEngine
from wrappers.cognition import ReflectionDiff
from wrappers.memory import MemoryStore
from wrappers.normalize import normalize
from wrappers.scrub import scrub
from wrappers.scrub import scrub_text
from wrappers.session import SessionStore

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _make_factory(structured_responses=None, complete_responses=None):
    """Build a MagicMock LLM factory with scripted responses."""

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
    cognition_config=None,
    agent_hub_tier=2,
):

    memory = MemoryStore(memory_dir=tmp_path / "kidecon" / "memory")
    sessions = SessionStore(
        sessions_dir=tmp_path / "kidecon" / "memory" / "sessions",
        window=12,
    )
    factory = factory or _make_factory()
    client = client or MagicMock()
    client.push_lesson.return_value = {"lesson_id": "les-1", "status": "queued"}
    safety = MagicMock()
    safety.check_ingress.return_value = (True, "ok")
    safety.check_egress.return_value = (True, "ok")
    return CognitiveEngine(
        factory=factory,
        safety=safety,
        models={
            "daily": "deepseek/deepseek-v4-flash",
            "strong": "deepseek/deepseek-pro",
            "coding": "qwen/qwen-3.7-max",
        },
        system_prompt="You are Hermes.",
        provider_name="openrouter",
        max_price=0.01,
        client=client,
        memory=memory,
        sessions=sessions,
        cognition_config={
            "reflect_on_daily": False,
            "soul_limit": 5000,
            "user_limit": 5000,
            "capabilities_limit": 3000,
            **(cognition_config or {}),
        },
        normalization_config={"llm_rewrite_on": [], "model": "daily"},
        agent_hub_tier=agent_hub_tier,
    )


def _make_message(text, source="discord", msg_id="msg-1", discord_user_id="42"):
    return {
        "id": msg_id,
        "type": "chat",
        "payload": {"text": text, "source": source, "discord_user_id": discord_user_id},
    }


REFLECTION_PAYLOAD = {
    "quality": 0.8,
    "critique": "Good answer.",
    "keep": ["User X prefers concise answers."],
    "self_edit": None,
    "lesson": None,
}


# ==================================================================
# C2 TEST 1: REFLECT appends a tagged entry to MEMORY.md + updates .index.json
# ==================================================================
class TestReflectAppendsMemory:
    def test_reflect_learn_appends_tagged_entry_and_updates_index(self, tmp_path):
        factory = _make_factory()
        engine = _build_engine(tmp_path, factory=factory)

        reflection = ReflectionDiff(
            quality=0.8,
            critique="ok",
            keep=["User X prefers concise answers."],
        )
        engine.learn(reflection)

        mem = engine.memory.read_memory()
        assert "User X prefers concise answers." in mem
        assert "## [reflection]" in mem

        index = engine.memory.read_index()
        assert "reflection" in index
        assert index["reflection"], "index should have a line range for the tag"
        assert "reflection" in index.get("tags_by_recency", [])


# ==================================================================
# C2 TEST 2: self_edit.persona over soul_limit is rejected
# ==================================================================
class TestSelfEditLimitEnforced:
    def test_persona_over_limit_rejected(self, tmp_path):
        engine = _build_engine(tmp_path, cognition_config={"soul_limit": 100})

        big_persona = "X" * 500
        reflection = ReflectionDiff(
            self_edit={"persona": big_persona, "human": None, "memory": []},
        )
        outcome = engine.learn(reflection)

        assert outcome["self_edit"]["persona"]["applied"] is False
        assert "rejected" in outcome["self_edit"]["persona"]["reason"]
        body = engine.memory.read_block("SOUL.md").body
        assert "X" * 500 not in body

    def test_persona_within_limit_applied(self, tmp_path):
        engine = _build_engine(tmp_path, cognition_config={"soul_limit": 5000})

        new_persona = "# Soul\nWarm but direct. Teaches by asking.\n"
        reflection = ReflectionDiff(
            self_edit={"persona": new_persona, "human": None, "memory": []},
        )
        outcome = engine.learn(reflection)

        assert outcome["self_edit"]["persona"]["applied"] is True
        assert engine.memory.read_block("SOUL.md").body == new_persona


# ==================================================================
# C2 TEST 3: simulated uncertain turn triggers replan once
# ==================================================================
class TestReplanOnUncertainty:
    def test_mid_step_uncertainty_triggers_replan_once(self, tmp_path):
        uncertain = "I can't help with that."
        still_uncertain = "I don't know the answer."
        good = "Here is a solid plan: step one, step two."

        classify = {
            "intent": "question",
            "complexity": "complex",
            "emotion": "neutral",
            "needs_tool": False,
            "needs_memory": False,
            "suggested_tier": "strong",
        }
        plan_first = {"steps": [{"action": "llm", "params": {}, "rationale": "first try"}]}
        plan_second = {"steps": [{"action": "llm", "params": {}, "rationale": "replanned"}]}

        factory = _make_factory(
            structured_responses=[classify, plan_first, plan_second],
            complete_responses=[uncertain, still_uncertain, good],
        )
        engine = _build_engine(tmp_path, factory=factory)

        msg = _make_message("/think complex question")
        engine.process(msg)

        plan_calls = [
            c
            for c in factory.complete_structured.call_args_list
            if c.kwargs.get("response_schema", {}).get("name") == "plan"
        ]
        assert len(plan_calls) == 2, "should plan once then replan once"
        llm_calls = factory.complete.call_args_list
        assert len(llm_calls) == 3, "should call llm: step(uncertain), escalate(uncertain), replanned(good)"


# ==================================================================
# C2 TEST 4: pushed lesson summary.example_before contains no real names
# ==================================================================
class TestLessonPlaceholderNames:
    def test_pushed_lesson_has_no_real_names(self, tmp_path):

        captured: dict = {}
        client = MagicMock()
        client.get_tier.return_value = 2

        def _capture(**kwargs):
            captured.update(kwargs)
            return {"lesson_id": "les-1", "status": "queued"}

        client.push_lesson.side_effect = _capture
        engine = _build_engine(tmp_path, client=client)

        # Inject a lesson with REAL PII to verify the edge scrub backstop redacts it.
        reflection = ReflectionDiff(
            quality=0.7,
            critique="ok",
            keep=[],
            lesson={
                "kind": "pattern",
                "title": "When User X asks about scheduling, email alice@example.com.",
                "summary": {
                    "what": "Contact bob@evil.com for help or call 555-123-4567.",
                    "why": "Reduces back-and-forth.",
                    "how_to_use": "Offer 3 slots.",
                    "example_before": "User X: is friday free? Email carol@test.org",
                    "example_after": "Here are 3 slots: ...",
                    "tier_hint": "daily",
                },
                "tags": ["scheduling"],
                "is_network_useful": True,
            },
        )
        engine.learn(reflection, context=None)

        client.push_lesson.assert_called_once()
        # Emails must be redacted in all pushed fields
        assert "alice@example.com" not in captured["title"]
        assert "bob@evil.com" not in captured["summary"]["what"]
        assert "555-123-4567" not in captured["summary"]["what"]
        assert "carol@test.org" not in captured["summary"]["example_before"]
        assert "[REDACTED]" in captured["summary"]["what"]
        # Tags should also be scrubbed
        assert all("@" not in t for t in captured["tags"])


# ==================================================================
# C2 TEST 5: persona survives restart (two turns across a restart)
# ==================================================================
class TestPersonaSurvivesRestart:
    def test_two_turns_across_restart_reuse_blocks_and_tail(self, tmp_path):
        memory = MemoryStore(memory_dir=tmp_path / "kidecon" / "memory")
        memory.ensure_default_blocks()
        memory.write_block("SOUL.md", "# Soul\nI am a patient teacher.\n")
        memory.write_block("USER.md", "# User\nLikes rockets.\n")

        sessions = SessionStore(
            sessions_dir=tmp_path / "kidecon" / "memory" / "sessions",
        )
        sessions.append("discord", "42", {"ts": "t1", "role": "user", "text": "hi", "tier": "daily"})
        sessions.append("discord", "42", {"ts": "t2", "role": "assistant", "text": "hello!", "tier": "daily"})

        # --- "restart": new engine instances, same on-disk memory dir ---
        engine2 = _build_engine(tmp_path)

        soul2 = engine2.memory.read_block("SOUL.md").body
        user2 = engine2.memory.read_block("USER.md").body
        assert "patient teacher" in soul2
        assert "Likes rockets." in user2

        tail = engine2.sessions.tail("discord", "42")
        assert len(tail) == 2
        assert tail[0]["text"] == "hi"
        assert tail[1]["text"] == "hello!"


# ==================================================================
# C2 TEST 6: edge scrub redacts email in summary.what
# ==================================================================
class TestScrubRedactsEmail:
    def test_scrub_redacts_email_in_summary(self):
        summary = {
            "what": "Contact alice@example.com for help.",
            "why": "She knows the system.",
            "example_before": "Email bob@evil.com now",
        }
        scrubbed = scrub(summary)
        assert "alice@example.com" not in scrubbed["what"]
        assert "[REDACTED]" in scrubbed["what"]
        assert "bob@evil.com" not in scrubbed["example_before"]

    def test_scrub_text_redacts_phone(self):
        text = "Call +1 (555) 123-4567 please"
        redacted = scrub_text(text)
        assert "555" not in redacted or "[REDACTED]" in redacted


# ==================================================================
# C2 TEST 7: failed push_lesson does not break a turn
# ==================================================================
class TestFailedPushDoesNotBreakTurn:
    def test_push_lesson_failure_returns_none(self, tmp_path):

        client = MagicMock()
        client.get_tier.return_value = 2
        client.push_lesson.side_effect = RuntimeError("hub down")

        engine = _build_engine(tmp_path, client=client)

        reflection = ReflectionDiff(
            quality=0.7,
            critique="ok",
            keep=[],
            lesson={
                "kind": "pattern",
                "title": "User X likes short answers.",
                "summary": {
                    "what": "User X wants brevity.",
                    "why": "Saves time.",
                    "how_to_use": "Keep it short.",
                    "example_before": "User X: explain",
                    "example_after": "short answer",
                    "tier_hint": "daily",
                },
                "tags": ["prefs"],
                "is_network_useful": True,
            },
        )
        # Must not raise
        outcome = engine.learn(reflection)
        assert outcome["lesson"] is None
        client.push_lesson.assert_called_once()

    def test_failed_push_does_not_break_full_turn(self, tmp_path):

        client = MagicMock()
        client.get_tier.return_value = 2
        client.push_lesson.side_effect = RuntimeError("hub down")
        client.respond_to_message.return_value = {}

        classify = {
            "intent": "question",
            "complexity": "moderate",
            "emotion": "neutral",
            "needs_tool": False,
            "needs_memory": False,
            "suggested_tier": "strong",
        }
        plan = {"steps": [{"action": "llm", "params": {}, "rationale": "answer"}]}
        reflection_payload = dict(REFLECTION_PAYLOAD)
        reflection_payload["lesson"] = {
            "kind": "pattern",
            "title": "User X likes brevity.",
            "summary": {
                "what": "User X wants brevity.",
                "why": "Saves time.",
                "how_to_use": "Keep it short.",
                "example_before": "User X: explain",
                "example_after": "short answer",
                "tier_hint": "daily",
            },
            "tags": ["prefs"],
            "is_network_useful": True,
        }
        factory = _make_factory(
            structured_responses=[classify, plan, reflection_payload],
            complete_responses=["Short answer."],
        )
        engine = _build_engine(tmp_path, factory=factory, client=client)

        msg = _make_message("/think explain quantum physics")
        # Must not raise even though push_lesson blows up
        engine.process(msg)

        client.respond_to_message.assert_called_once()
        result_text = client.respond_to_message.call_args[1]["result"]["text"]
        assert result_text == "Short answer."


# ==================================================================
# C1 TEST: daily latency parity — keyword normalization, 0 LLM on daily
# ==================================================================
class TestDailyLatencyParity:
    def test_daily_does_not_call_structured_llm(self, tmp_path):
        factory = _make_factory(complete_responses=["Quick answer."])
        engine = _build_engine(tmp_path, factory=factory, agent_hub_tier=1)

        msg = _make_message("What is 2+2?")
        engine.process(msg)

        # daily path: no structured calls (no ORIENT/PLAN/REFLECT LLM)
        factory.complete_structured.assert_not_called()
        factory.complete.assert_called_once()


# ==================================================================
# C1 TEST: normalized sidecar stored alongside raw; LLM saw raw
# ==================================================================
class TestNormalizationSidecar:
    def test_daily_keyword_normalization_no_llm(self):
        result = normalize("schedule a meeting tomorrow", do_llm_rewrite=False)
        assert result.source == "keyword"
        assert result.resolved_domain_id == "SCHEDULING"
        assert result.normalized_text == "schedule a meeting tomorrow"  # raw preserved

    def test_llm_always_sees_raw(self, tmp_path):
        factory = _make_factory(complete_responses=["Response."])
        engine = _build_engine(tmp_path, factory=factory, agent_hub_tier=1)

        msg = _make_message("schedule a meeting")
        engine.process(msg)

        call = factory.complete.call_args
        messages = call.kwargs["messages"]
        user_msg = [m for m in messages if m["role"] == "user"][-1]
        assert user_msg["content"] == "schedule a meeting"  # raw, not normalized


# ==================================================================
# C1 TEST: reflect_on_daily=false skips reflection on daily tier
# ==================================================================
class TestReflectOnDaily:
    def test_daily_skips_reflection_by_default(self, tmp_path):
        reflection_payload = dict(REFLECTION_PAYLOAD)
        factory = _make_factory(
            structured_responses=[reflection_payload],
            complete_responses=["Answer."],
        )
        engine = _build_engine(tmp_path, factory=factory, agent_hub_tier=1)

        msg = _make_message("hello")
        engine.process(msg)

        reflect_calls = [
            c
            for c in factory.complete_structured.call_args_list
            if c.kwargs.get("response_schema", {}).get("name") == "reflection"
        ]
        assert len(reflect_calls) == 0, "daily should not reflect by default"


# ==================================================================
# BLOCKER fix: REFLECT/LEARN only after egress clears (spec §8.3)
# ==================================================================
class TestEgressBeforeReflect:
    def test_egress_blocked_skips_reflection(self, tmp_path):
        """An egress-blocked result must not be learned into persona/memory."""
        safety = MagicMock()
        safety.check_ingress.return_value = (True, "ok")
        safety.check_egress.return_value = (False, "unsafe content")
        engine = _build_engine(tmp_path)
        engine.safety = safety

        reflection_payload = {
            "quality": 0.9,
            "critique": "ok",
            "keep": ["User X likes brevity."],
            "self_edit": {"persona": "# Soul\nShould NOT be written.\n", "human": None, "memory": []},
            "lesson": None,
        }
        factory = _make_factory(
            structured_responses=[reflection_payload],
            complete_responses=["Dangerous content"],
        )
        engine.factory = factory

        msg = _make_message("/think something")
        engine.process(msg)

        # The unsafe response should NOT be reflected into memory
        soul = engine.memory.read_block("SOUL.md").body
        assert "Should NOT be written" not in soul
        mem = engine.memory.read_memory()
        assert "User X likes brevity." not in mem


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
