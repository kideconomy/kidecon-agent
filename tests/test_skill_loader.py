import logging
from unittest.mock import MagicMock

import pytest

from wrappers.skill_loader import SkillLoader
from wrappers.skill_loader import merge_skill_config

logger = logging.getLogger(__name__)


def _mock_client():
    client = MagicMock()
    client.discover_skills.return_value = [
        {
            "id": "sk-clickup-ticket",
            "name": "clickup-ticket",
            "category": "tool",
            "description": "Create ClickUp tickets for bug reports and feature requests",
            "version": "1.0.0",
        },
        {
            "id": "sk-search",
            "name": "knowledge-search",
            "category": "knowledge",
            "description": "Search the knowledge base for answers",
            "version": "1.0.0",
        },
    ]
    client.get_skill.return_value = {
        "id": "sk-clickup-ticket",
        "name": "clickup-ticket",
        "instructions": "## ClickUp Ticket Procedure\n\n1. Ask for the summary\n2. Ask for the description\n3. Ask for priority\n4. Call the handler\n5. Confirm creation",
    }
    return client


def test_refresh_loads_index():
    client = _mock_client()
    loader = SkillLoader(client)
    loader.refresh()
    assert len(loader._index) == 2
    client.discover_skills.assert_called_once_with("")


def test_get_index_summary():
    client = _mock_client()
    loader = SkillLoader(client)
    loader.refresh()
    summary = loader.get_index_summary()
    assert "## Available Skills" in summary
    assert "clickup-ticket" in summary
    assert "knowledge-search" in summary


def test_get_index_summary_empty():
    client = _mock_client()
    loader = SkillLoader(client)
    assert loader.get_index_summary() == ""


def test_get_skill_instructions_lazy_loads():
    client = _mock_client()
    loader = SkillLoader(client)
    loader._index = client.discover_skills.return_value
    instructions = loader.get_skill_instructions("sk-clickup-ticket")
    assert instructions is not None
    assert "ClickUp Ticket Procedure" in instructions
    client.get_skill.assert_called_once_with("sk-clickup-ticket")


def test_get_skill_instructions_caches():
    client = _mock_client()
    loader = SkillLoader(client)
    loader._index = client.discover_skills.return_value
    loader.get_skill_instructions("sk-clickup-ticket")
    loader.get_skill_instructions("sk-clickup-ticket")
    client.get_skill.assert_called_once_with("sk-clickup-ticket")


def test_get_skill_instructions_returns_none_on_404():
    client = _mock_client()
    client.get_skill.return_value = None
    loader = SkillLoader(client)
    assert loader.get_skill_instructions("sk-nonexistent") is None


def test_get_skill_tools_returns_declared_tools():
    client = _mock_client()
    client.get_skill.return_value = {
        "id": "sk-clickup-ticket",
        "name": "clickup-ticket",
        "instructions": "procedure",
        "tools": ["message_user", "hub:clickup.create"],
        "min_hub_tier": 0,
        "blocked": False,
    }
    loader = SkillLoader(client)
    loader._index = client.discover_skills.return_value
    assert loader.get_skill_tools("sk-clickup-ticket") == ["message_user", "hub:clickup.create"]


def test_get_skill_tools_returns_none_when_undeclared():
    client = _mock_client()
    loader = SkillLoader(client)
    loader._index = client.discover_skills.return_value
    assert loader.get_skill_tools("sk-clickup-ticket") is None


def test_get_skill_tools_returns_none_on_404():
    client = _mock_client()
    client.get_skill.return_value = None
    loader = SkillLoader(client)
    assert loader.get_skill_tools("sk-nonexistent") is None


def test_find_skill_matches_name():
    client = _mock_client()
    loader = SkillLoader(client)
    loader.refresh()
    result = loader.find_skill("I need to report a bug using clickup-ticket")
    assert result is not None
    assert result["name"] == "clickup-ticket"


def test_find_skill_no_match():
    client = _mock_client()
    loader = SkillLoader(client)
    loader.refresh()
    result = loader.find_skill("hello, how are you?")
    assert result is None


def test_find_skill_case_insensitive():
    client = _mock_client()
    loader = SkillLoader(client)
    loader.refresh()
    result = loader.find_skill("CLICKUP-TICKET is what I need")
    assert result is not None
    assert result["name"] == "clickup-ticket"


def test_refresh_logs_count(caplog):
    caplog.set_level(logging.INFO)
    client = _mock_client()
    loader = SkillLoader(client)
    loader.refresh()
    assert "Loaded 2 skills from hub" in caplog.text


def test_find_skill_handles_empty_index():
    client = _mock_client()
    loader = SkillLoader(client)
    result = loader.find_skill("clickup-ticket")
    assert result is None


# ------------------------------------------------------------------
# Defense-in-depth: client-side tier/block filtering
# ------------------------------------------------------------------
def _tiered_client(tier: int):
    client = MagicMock()
    client.get_tier.return_value = tier
    client.discover_skills.return_value = [
        {
            "id": "sk-public",
            "name": "public-skill",
            "category": "tool",
            "description": "Anyone can use this",
            "version": "1.0.0",
            "min_hub_tier": 0,
            "blocked": False,
        },
        {
            "id": "sk-staff",
            "name": "staff-skill",
            "category": "tool",
            "description": "Staff only",
            "version": "1.0.0",
            "min_hub_tier": 3,
            "blocked": False,
        },
        {
            "id": "sk-danger",
            "name": "danger-skill",
            "category": "tool",
            "description": "Quarantined",
            "version": "1.0.0",
            "min_hub_tier": 0,
            "blocked": True,
        },
    ]
    return client


def test_refresh_drops_out_of_tier_and_blocked_for_tier1():
    client = _tiered_client(1)
    loader = SkillLoader(client)
    loader.refresh()
    ids = {s["id"] for s in loader._index}
    assert ids == {"sk-public"}


def test_refresh_keeps_staff_skill_for_tier3():
    client = _tiered_client(3)
    loader = SkillLoader(client)
    loader.refresh()
    ids = {s["id"] for s in loader._index}
    assert "sk-public" in ids
    assert "sk-staff" in ids
    # blocked is dropped even for tier 3
    assert "sk-danger" not in ids


def test_get_skill_instructions_drops_out_of_tier():
    client = _tiered_client(1)
    client.get_skill.return_value = {
        "id": "sk-staff",
        "name": "staff-skill",
        "instructions": "secret staff procedure",
        "min_hub_tier": 3,
        "blocked": False,
    }
    loader = SkillLoader(client)
    loader._agent_tier = 1
    assert loader.get_skill_instructions("sk-staff") is None


def test_get_skill_instructions_drops_blocked():
    client = _tiered_client(3)
    client.get_skill.return_value = {
        "id": "sk-danger",
        "name": "danger-skill",
        "instructions": "dangerous procedure",
        "min_hub_tier": 0,
        "blocked": True,
    }
    loader = SkillLoader(client)
    loader._agent_tier = 3
    assert loader.get_skill_instructions("sk-danger") is None


def test_get_skill_instructions_keeps_accessible():
    client = _tiered_client(1)
    client.get_skill.return_value = {
        "id": "sk-public",
        "name": "public-skill",
        "instructions": "public procedure",
        "min_hub_tier": 0,
        "blocked": False,
    }
    loader = SkillLoader(client)
    loader._agent_tier = 1
    assert loader.get_skill_instructions("sk-public") == "public procedure"


def test_refresh_defaults_to_tier0_on_tier_lookup_failure():
    client = _tiered_client(1)
    client.get_tier.side_effect = RuntimeError("hub down")
    loader = SkillLoader(client)
    loader.refresh()
    # tier 0 keeps only public, drops staff + blocked
    ids = {s["id"] for s in loader._index}
    assert ids == {"sk-public"}


def test_vector_find_drops_inaccessible_match():
    client = _tiered_client(1)
    client.discover_skills.return_value = [
        {
            "id": "sk-staff",
            "name": "staff-skill",
            "category": "tool",
            "description": "Staff only",
            "version": "1.0.0",
            "min_hub_tier": 3,
            "blocked": False,
            "score": 0.9,
        },
    ]
    loader = SkillLoader(client)
    loader._agent_tier = 1
    assert loader.find_skill("I need the staff-skill") is None


def test_refresh_re_resolves_tier_after_promotion():
    """A mid-session promotion (tier 1 -> 3) must take effect on the next refresh.

    refresh() invalidates the cached tier so staff skills the hub now returns
    are retained, not dropped against a stale tier-1 cache.
    """
    client = _tiered_client(1)
    loader = SkillLoader(client)
    loader._agent_tier = 1
    loader.refresh()
    assert "sk-staff" not in {s["id"] for s in loader._index}

    # Promote: hub now reports tier 3 and returns the staff skill as accessible.
    client.get_tier.return_value = 3
    loader.refresh()
    ids = {s["id"] for s in loader._index}
    assert "sk-staff" in ids
    assert "sk-public" in ids
    assert "sk-danger" not in ids  # blocked still dropped even for tier 3


def test_get_skill_instructions_evicts_cache_on_demotion():
    """A cached staff skill must not be served after the agent is demoted to tier 1."""
    client = _tiered_client(3)
    client.get_skill.return_value = {
        "id": "sk-staff",
        "name": "staff-skill",
        "instructions": "secret staff procedure",
        "min_hub_tier": 3,
        "blocked": False,
    }
    loader = SkillLoader(client)
    loader._agent_tier = 3
    # First fetch caches the staff instructions while tier 3.
    assert loader.get_skill_instructions("sk-staff") == "secret staff procedure"

    # Demote: the cached entry must be re-checked and evicted.
    loader._agent_tier = 1
    assert loader.get_skill_instructions("sk-staff") is None
    assert "sk-staff" not in loader._cache


# ------------------------------------------------------------------
# Per-skill config: retention, merge, and resolution
# ------------------------------------------------------------------
def _config_client(config=None):
    client = MagicMock()
    client.discover_skills.return_value = [
        {
            "id": "sk-docs",
            "name": "legal-doc-compare",
            "category": "documentation",
            "description": "docs mirror",
            "version": "1.0.0",
            "min_hub_tier": 0,
            "blocked": False,
        },
    ]
    client.get_skill.return_value = {
        "id": "sk-docs",
        "name": "legal-doc-compare",
        "instructions": "procedure",
        "tools": ["docs_sync"],
        "config": config or {"docs": {"enabled": True, "branch": "main", "subfolder": "legal-docs"}},
        "min_hub_tier": 0,
        "blocked": False,
    }
    return client


def test_merge_skill_config_deep_merges_nested():
    defaults = {"docs": {"enabled": True, "branch": "main"}, "timeout": 15}
    overrides = {"docs": {"branch": "release"}, "timeout": 30}
    merged = merge_skill_config(defaults, overrides)
    assert merged == {"docs": {"enabled": True, "branch": "release"}, "timeout": 30}
    # inputs are not mutated
    assert defaults == {"docs": {"enabled": True, "branch": "main"}, "timeout": 15}


def test_merge_skill_config_non_dict_override_replaces():
    assert merge_skill_config({"docs": {"x": 1}}, {"docs": "flat"}) == {"docs": "flat"}


def test_merge_skill_config_adds_new_keys():
    assert merge_skill_config({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_get_skill_config_returns_raw_config():
    client = _config_client()
    loader = SkillLoader(client)
    assert loader.get_skill_config("sk-docs") == {
        "docs": {"enabled": True, "branch": "main", "subfolder": "legal-docs"},
    }


def test_get_skill_config_returns_none_on_404():
    client = MagicMock()
    client.get_skill.return_value = None
    loader = SkillLoader(client)
    assert loader.get_skill_config("sk-missing") is None


def test_resolve_skill_config_returns_defaults_without_local():
    client = _config_client()
    loader = SkillLoader(client)
    assert loader.resolve_skill_config("sk-docs") == {
        "docs": {"enabled": True, "branch": "main", "subfolder": "legal-docs"},
    }


def test_resolve_skill_config_merges_local_overrides():
    client = _config_client()
    loader = SkillLoader(client)
    local = {"skills": {"legal-doc-compare": {"config": {"docs": {"branch": "release"}}}}}
    resolved = loader.resolve_skill_config("sk-docs", local)
    assert resolved == {"docs": {"enabled": True, "branch": "release", "subfolder": "legal-docs"}}


def test_resolve_skill_config_local_wins_on_leaf_values():
    client = _config_client()
    loader = SkillLoader(client)
    local = {"skills": {"legal-doc-compare": {"config": {"docs": {"enabled": False}}}}}
    resolved = loader.resolve_skill_config("sk-docs", local)
    assert resolved["docs"]["enabled"] is False
    assert resolved["docs"]["branch"] == "main"


def test_resolve_skill_config_returns_none_without_any_config():
    client = MagicMock()
    client.get_skill.return_value = {
        "id": "sk-noconfig",
        "name": "plain-skill",
        "instructions": "x",
        "min_hub_tier": 0,
        "blocked": False,
    }
    loader = SkillLoader(client)
    assert loader.resolve_skill_config("sk-noconfig") is None


def test_find_skill_by_name_case_insensitive():
    client = _config_client()
    loader = SkillLoader(client)
    loader.refresh()
    assert loader.find_skill_by_name("LEGAL-DOC-COMPARE")["id"] == "sk-docs"
    assert loader.find_skill_by_name("nonexistent") is None
