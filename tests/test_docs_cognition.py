"""Tests for the docs-mirror cognition-loop integration.

Covers: local_tool dispatch for docs_sync and text_diff, the docs_sync
transparency messages (disabled / blocked / stale / unexpected error),
_trace_touches_docs detection, egress running on docs-bearing turns for
non-Discord sources, backward compatibility (no docs_mirror kwarg), and an
end-to-end process() turn with a docs_sync step.
"""

import logging
from unittest.mock import MagicMock

from wrappers import tools
from wrappers.cognition import CognitiveEngine
from wrappers.cognition import Step
from wrappers.cognition import _skill_tool_name
from wrappers.cognition import _trace_touches_docs
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
    docs_mirror=None,
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
        docs_mirror=docs_mirror,
    )


# ------------------------------------------------------------------
# docs_sync dispatch
# ------------------------------------------------------------------
def test_docs_sync_reports_successful_refresh(tmp_path):
    mirror = MagicMock()
    mirror.branch = "main"
    mirror.dir = tmp_path / "legal-docs"
    mirror.sync.return_value = {
        "ok": True,
        "cloned": False,
        "fresh": True,
        "commit": "abc1234def5678",
        "error": None,
        "warning": None,
    }
    engine = _build_engine(tmp_path, docs_mirror=mirror)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "docs_sync"}),
        messages=[],
        context=MagicMock(),
    )
    mirror.sync.assert_called_once_with(3)
    assert "up to date" in output
    assert "abc1234def56" in output
    assert "main" in output


def test_docs_sync_relays_block_message(tmp_path):
    mirror = MagicMock()
    mirror.sync.return_value = {
        "ok": False,
        "error": "Docs mirror sync was blocked. Reason: staff-only. To proceed: ask admin.",
    }
    engine = _build_engine(tmp_path, agent_hub_tier=1, docs_mirror=mirror)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "docs_sync"}),
        messages=[],
        context=MagicMock(),
    )
    assert "blocked" in output
    assert "To proceed:" in output


def test_docs_sync_surfaces_staleness_warning(tmp_path):
    mirror = MagicMock()
    mirror.branch = "main"
    mirror.dir = tmp_path / "legal-docs"
    mirror.sync.return_value = {
        "ok": True,
        "cloned": False,
        "fresh": False,
        "commit": "abc1234",
        "error": None,
        "warning": "Docs mirror refresh failed — continuing with the last local copy. Reason: x. To proceed: y.",
    }
    engine = _build_engine(tmp_path, docs_mirror=mirror)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "docs_sync"}),
        messages=[],
        context=MagicMock(),
    )
    assert "last local copy" in output


def test_docs_sync_skipped_when_mirror_is_none(tmp_path):
    engine = _build_engine(tmp_path, docs_mirror=None)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "docs_sync"}),
        messages=[],
        context=MagicMock(),
    )
    assert "skipped" in output
    assert "kidecon key add --name github-docs" in output


def test_docs_sync_unexpected_error_is_transparent(tmp_path):
    mirror = MagicMock()
    mirror.sync.side_effect = RuntimeError("boom")
    engine = _build_engine(tmp_path, docs_mirror=mirror)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "docs_sync"}),
        messages=[],
        context=MagicMock(),
    )
    assert "unexpected error" in output
    assert "To proceed:" in output


# ------------------------------------------------------------------
# text_diff dispatch
# ------------------------------------------------------------------
def test_text_diff_dispatch_routes_to_tools(tmp_path, monkeypatch):
    tools.set_workspace_dir(tmp_path)
    (tmp_path / "a.md").write_text("one\n")
    (tmp_path / "b.md").write_text("two\n")
    engine = _build_engine(tmp_path)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "text_diff", "path_a": "a.md", "path_b": "b.md"}),
        messages=[],
        context=MagicMock(),
    )
    assert "-one" in output
    assert "+two" in output


def test_unknown_local_tool_still_reported(tmp_path):
    engine = _build_engine(tmp_path)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "nope"}),
        messages=[],
        context=MagicMock(),
    )
    assert output == "unknown local tool: nope"


# ------------------------------------------------------------------
# staff-only read gate on the mirror (file_read / text_diff)
# ------------------------------------------------------------------
def test_file_read_under_mirror_blocked_for_non_staff(tmp_path, monkeypatch):
    tools.set_workspace_dir(tmp_path)
    (tmp_path / "legal-docs").mkdir()
    (tmp_path / "legal-docs" / "secret.md").write_text("corpus\n")
    engine = _build_engine(tmp_path, agent_hub_tier=1, docs_mirror=None)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "file_read", "path": "legal-docs/secret.md"}),
        messages=[],
        context=MagicMock(),
    )
    assert "Docs read was blocked" in output
    assert "your tier: 1" in output
    assert "To proceed:" in output


def test_file_read_under_mirror_allowed_for_staff(tmp_path, monkeypatch):
    tools.set_workspace_dir(tmp_path)
    (tmp_path / "legal-docs").mkdir()
    (tmp_path / "legal-docs" / "doc.md").write_text("corpus text\n")
    engine = _build_engine(tmp_path, agent_hub_tier=3, docs_mirror=None)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "file_read", "path": "legal-docs/doc.md"}),
        messages=[],
        context=MagicMock(),
    )
    assert output == "corpus text\n"


def test_file_read_outside_mirror_not_gated_for_non_staff(tmp_path, monkeypatch):
    tools.set_workspace_dir(tmp_path)
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "note.md").write_text("hello\n")
    engine = _build_engine(tmp_path, agent_hub_tier=1, docs_mirror=None)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "file_read", "path": "inbox/note.md"}),
        messages=[],
        context=MagicMock(),
    )
    assert output == "hello\n"


def test_text_diff_blocked_for_non_staff_when_one_side_is_corpus(tmp_path, monkeypatch):
    tools.set_workspace_dir(tmp_path)
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "outside.md").write_text("x\n")
    (tmp_path / "legal-docs").mkdir()
    (tmp_path / "legal-docs" / "doc.md").write_text("y\n")
    engine = _build_engine(tmp_path, agent_hub_tier=2, docs_mirror=None)
    output = engine._dispatch_step(
        Step(
            action="local_tool",
            params={"name": "text_diff", "path_a": "inbox/outside.md", "path_b": "legal-docs/doc.md"},
        ),
        messages=[],
        context=MagicMock(),
    )
    assert "Docs read was blocked" in output


def test_symlink_into_mirror_is_gated(tmp_path, monkeypatch):
    tools.set_workspace_dir(tmp_path)
    (tmp_path / "inbox").mkdir()
    (tmp_path / "legal-docs").mkdir()
    (tmp_path / "legal-docs" / "secret.md").write_text("corpus\n")
    (tmp_path / "inbox" / "link.md").symlink_to(tmp_path / "legal-docs" / "secret.md")
    engine = _build_engine(tmp_path, agent_hub_tier=1, docs_mirror=None)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "file_read", "path": "inbox/link.md"}),
        messages=[],
        context=MagicMock(),
    )
    assert "Docs read was blocked" in output


def test_read_gate_uses_real_mirror_min_tier(tmp_path, monkeypatch):
    from wrappers.docs_mirror import DocsMirror

    tools.set_workspace_dir(tmp_path)
    (tmp_path / "legal-docs").mkdir()
    (tmp_path / "legal-docs" / "doc.md").write_text("corpus\n")
    mirror = DocsMirror(mirror_dir=tmp_path / "legal-docs")
    engine = _build_engine(tmp_path, agent_hub_tier=2, docs_mirror=mirror)
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "file_read", "path": "legal-docs/doc.md"}),
        messages=[],
        context=MagicMock(),
    )
    assert "Docs read was blocked" in output


# ------------------------------------------------------------------
# _trace_touches_docs
# ------------------------------------------------------------------
def test_trace_touches_docs_detects_docs_sync():
    trace = [{"action": "local_tool", "params": {"name": "docs_sync"}}]
    assert _trace_touches_docs(trace) is True


def test_trace_touches_docs_detects_file_read_under_mirror():
    trace = [{"action": "local_tool", "params": {"name": "file_read", "path": "legal-docs/01_corpus/x.md"}}]
    assert _trace_touches_docs(trace) is True


def test_trace_touches_docs_detects_text_diff_under_mirror():
    trace = [
        {
            "action": "local_tool",
            "params": {"name": "text_diff", "path_a": "inbox/outside.md", "path_b": "legal-docs/01_corpus/x.md"},
        },
    ]
    assert _trace_touches_docs(trace) is True


def test_trace_touches_docs_ignores_other_reads():
    trace = [{"action": "local_tool", "params": {"name": "file_read", "path": "inbox/x.md"}}]
    assert _trace_touches_docs(trace) is False


def test_trace_touches_docs_ignores_non_local_steps():
    trace = [{"action": "lexor_call", "params": {"tool": "search.semantic"}}]
    assert _trace_touches_docs(trace) is False


def test_trace_touches_docs_follows_symlink_into_mirror(tmp_path, monkeypatch):
    tools.set_workspace_dir(tmp_path)
    (tmp_path / "inbox").mkdir()
    (tmp_path / "legal-docs").mkdir()
    (tmp_path / "legal-docs" / "secret.md").write_text("corpus\n")
    (tmp_path / "inbox" / "link.md").symlink_to(tmp_path / "legal-docs" / "secret.md")
    trace = [{"action": "local_tool", "params": {"name": "file_read", "path": "inbox/link.md"}}]
    assert _trace_touches_docs(trace) is True


def test_trace_touches_docs_honors_custom_mirror_dir(tmp_path, monkeypatch):
    tools.set_workspace_dir(tmp_path)
    (tmp_path / "custom-corpus").mkdir()
    (tmp_path / "custom-corpus" / "doc.md").write_text("x\n")
    trace = [{"action": "local_tool", "params": {"name": "file_read", "path": "custom-corpus/doc.md"}}]
    assert _trace_touches_docs(trace) is False
    assert _trace_touches_docs(trace, mirror_dir=tmp_path / "custom-corpus") is True


# ------------------------------------------------------------------
# egress on docs-bearing turns
# ------------------------------------------------------------------
def test_check_egress_runs_for_docs_turn_non_discord_source(tmp_path):
    safety = MagicMock()
    safety.check_egress.return_value = (True, "ok")
    engine = _build_engine(tmp_path, safety=safety)
    passed, _ = engine._check_egress("a2a", "some result", "msg-1", used_docs=True)
    assert passed is True
    safety.check_egress.assert_called_once()


def test_check_egress_blocks_docs_turn_non_discord_source(tmp_path):
    safety = MagicMock()
    safety.check_egress.return_value = (False, "blocked-reason")
    engine = _build_engine(tmp_path, safety=safety)
    original = "ORIGINAL_CORPUS_TEXT"
    passed, result = engine._check_egress("a2a", original, "msg-1", used_docs=True)
    assert passed is False
    assert original not in result


def test_check_egress_skips_when_not_discord_no_lexor_no_docs(tmp_path):
    safety = MagicMock()
    engine = _build_engine(tmp_path, safety=safety)
    engine._check_egress("a2a", "result", "msg-1")
    safety.check_egress.assert_not_called()


# ------------------------------------------------------------------
# backward compatibility
# ------------------------------------------------------------------
def test_engine_constructs_without_docs_mirror_kwarg(tmp_path):
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
    assert engine.docs_mirror is None


# ------------------------------------------------------------------
# end-to-end: process() with docs_sync + file_read steps
# ------------------------------------------------------------------
def test_process_with_docs_steps_runs_egress(tmp_path, monkeypatch):
    mirror = MagicMock()
    mirror.branch = "main"
    mirror.dir = tmp_path / "legal-docs"
    mirror.sync.return_value = {
        "ok": True,
        "cloned": False,
        "fresh": True,
        "commit": "abc1234def5678",
        "error": None,
        "warning": None,
    }
    plan_response = {
        "steps": [
            {"action": "local_tool", "params": {"name": "docs_sync"}, "rationale": "refresh corpus"},
            {
                "action": "local_tool",
                "params": {"name": "file_read", "path": "legal-docs/01_corpus/protocol/lexicon.md"},
                "rationale": "read candidate",
            },
            {"action": "llm", "params": {"model": "m/s"}, "rationale": "gap analysis"},
        ],
    }
    factory = _make_factory(
        structured_responses=[
            {
                "intent": "compare documents",
                "complexity": "moderate",
                "emotion": "neutral",
                "needs_tool": True,
                "needs_memory": False,
                "suggested_tier": "strong",
            },
            plan_response,
            {"quality": 0.8, "critique": "ok", "keep": [], "self_edit": None, "lesson": None},
        ],
        complete_responses=["The checklist is missing our securities section."],
    )
    safety = MagicMock()
    safety.check_ingress.return_value = (True, "ok")
    safety.check_egress.return_value = (True, "ok")
    engine = _build_engine(tmp_path, factory=factory, docs_mirror=mirror, safety=safety)

    # file_read must resolve inside the isolated workspace.
    from wrappers import tools as tools_mod

    workspace = tmp_path / "workspace"
    (workspace / "legal-docs" / "01_corpus" / "protocol").mkdir(parents=True)
    (workspace / "legal-docs" / "01_corpus" / "protocol" / "lexicon.md").write_text("corpus text\n")
    tools_mod.set_workspace_dir(workspace)

    message = {
        "id": "msg-docs-1",
        "type": "chat",
        "payload": {
            "text": "/think Compare this checklist to our docs",
            "source": "a2a",
        },
    }
    engine.process(message)

    mirror.sync.assert_called_once()
    # a2a normally skips egress; the docs-bearing trace must force it.
    safety.check_egress.assert_called_once()
    engine.client.respond_to_message.assert_called_once()
    sent_result = engine.client.respond_to_message.call_args.kwargs["result"]["text"]
    assert "securities" in sent_result


# ------------------------------------------------------------------
# skill tool gating (definition.tools enforcement)
# ------------------------------------------------------------------
def test_skill_tool_gate_blocks_undeclared_local_tool(tmp_path):
    engine = _build_engine(tmp_path)
    context = MagicMock()
    context.skill_tools = ["message_user"]
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "docs_sync"}),
        messages=[],
        context=context,
    )
    assert "blocked" in output
    assert "docs_sync" in output


def test_skill_tool_gate_allows_declared_tool(tmp_path):
    engine = _build_engine(tmp_path)
    context = MagicMock()
    context.skill_tools = ["docs_sync"]
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "docs_sync"}),
        messages=[],
        context=context,
    )
    assert "blocked" not in output


def test_skill_tool_gate_skipped_when_no_tools_declared(tmp_path):
    engine = _build_engine(tmp_path)
    context = MagicMock()
    context.skill_tools = None
    output = engine._dispatch_step(
        Step(action="local_tool", params={"name": "docs_sync"}),
        messages=[],
        context=context,
    )
    assert "blocked" not in output


def test_skill_tool_name_maps_namespaces():
    assert _skill_tool_name("message_user", {}) == "message_user"
    assert _skill_tool_name("local_tool", {"name": "docs_sync"}) == "docs_sync"
    assert _skill_tool_name("lexor_call", {"tool": "search.semantic"}) == "lexor:search.semantic"
    assert _skill_tool_name("hub_call", {"tool": "docs.search"}) == "hub:docs.search"
    assert _skill_tool_name("llm", {}) is None
    assert _skill_tool_name("memory_write", {}) is None
