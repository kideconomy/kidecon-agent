import logging
from unittest.mock import MagicMock

import pytest

from wrappers.skill_loader import SkillLoader

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
