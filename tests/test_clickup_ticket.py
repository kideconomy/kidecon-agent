"""Tests for the clickup-ticket skill: clickup_client.py and handler.py."""

import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from skills.clickup_ticket.clickup_client import ClickUpClient
from skills.clickup_ticket.clickup_client import ClickUpError
from skills.clickup_ticket.clickup_client import build_task_url
from skills.clickup_ticket.clickup_client import format_description
from skills.clickup_ticket.handler import _build_custom_fields
from skills.clickup_ticket.handler import _resolve_list_id
from skills.clickup_ticket.handler import run

# -- ClickUpClient -----------------------------------------------------------


class TestClickUpClientInit:
    def test_requires_token(self):
        with pytest.raises(ClickUpError, match="No ClickUp API token"):
            ClickUpClient("")

    def test_accepts_token(self):
        client = ClickUpClient("pk_test")
        assert client._token == "pk_test"


class TestClickUpClientGetUser:
    def test_success(self):
        client = ClickUpClient("pk_test")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user": {"username": "testuser", "id": 123}}
        with patch("httpx.get", return_value=mock_response):
            result = client.get_user()
        assert result["username"] == "testuser"

    def test_invalid_token_raises(self):
        client = ClickUpClient("pk_bad")
        mock_response = MagicMock()
        mock_response.status_code = 401
        with patch("httpx.get", return_value=mock_response):
            with pytest.raises(ClickUpError, match="HTTP 401"):
                client.get_user()


class TestClickUpClientCreateTask:
    def test_success(self):
        client = ClickUpClient("pk_test")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "task123", "url": "https://app.clickup.com/t/123/task123"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = client.create_task("list456", "My Bug", description="desc", priority="urgent")
        assert result["id"] == "task123"
        call_args = mock_post.call_args
        body = call_args.kwargs["json"]
        assert body["name"] == "My Bug"
        assert body["priority"] == 1
        assert body["notify_all"] is True
        assert body["check_required_custom_fields"] is False

    def test_failure_raises(self):
        client = ClickUpClient("pk_test")
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(ClickUpError, match="HTTP 400"):
                client.create_task("list456", "My Bug")

    def test_custom_fields_included(self):
        client = ClickUpClient("pk_test")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "task123"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_task(
                "list456",
                "My Bug",
                custom_fields=[{"id": "field-1", "value": "high"}],
            )
        body = mock_post.call_args.kwargs["json"]
        assert body["custom_fields"] == [{"id": "field-1", "value": "high"}]

    def test_assignees_included(self):
        client = ClickUpClient("pk_test")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "task123"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_task("list456", "My Bug", assignees=[111, 222])
        body = mock_post.call_args.kwargs["json"]
        assert body["assignees"] == [111, 222]


# -- build_task_url ----------------------------------------------------------


class TestBuildTaskUrl:
    def test_with_team_id(self):
        url = build_task_url("team999", "task123")
        assert url == "https://app.clickup.com/tteam999/task123"

    def test_without_team_id(self):
        url = build_task_url("", "task123")
        assert url == "https://app.clickup.com/t/task123"


# -- format_description ------------------------------------------------------


class TestFormatDescription:
    def test_all_sections(self):
        desc = format_description(
            "Something broke",
            reproduction_steps="1. Do thing\n2. Do other thing",
            expected="It should work",
            actual="It crashed",
            environment="Chrome 120, macOS",
        )
        assert "Something broke" in desc
        assert "**Steps to reproduce**" in desc
        assert "**Expected**" in desc
        assert "**Actual**" in desc
        assert "**Environment**" in desc

    def test_only_base(self):
        desc = format_description("Just a note")
        assert desc == "Just a note"

    def test_empty(self):
        assert format_description() == ""


# -- handler helpers ---------------------------------------------------------


class TestResolveListId:
    def test_found_in_map(self):
        config = {"list_map": {"bug": "list1", "feature": "list2"}, "default_list_id": "default"}
        assert _resolve_list_id("bug", config) == "list1"

    def test_falls_back_to_default(self):
        config = {"list_map": {"bug": "list1"}, "default_list_id": "default"}
        assert _resolve_list_id("feature", config) == "default"

    def test_no_config(self):
        assert _resolve_list_id("bug", {}) == ""

    def test_string_list_map_parsed(self):
        config = {"list_map": '{"bug": "list1"}', "default_list_id": "default"}
        assert _resolve_list_id("bug", config) == "list1"


class TestBuildCustomFields:
    def test_empty_returns_none(self):
        assert _build_custom_fields({}, {}) is None

    def test_from_config_map(self):
        """Config map provides UUID resolution; agent must supply values."""
        config = {"custom_field_map": {"severity": "uuid-123"}}
        payload = {"custom_fields": {"severity": "high"}}
        result = _build_custom_fields(payload, config)
        assert result == [{"id": "uuid-123", "value": "high"}]

    def test_resolves_through_map(self):
        """Agent label passed through config map to get ClickUp UUID."""
        config = {"custom_field_map": {"severity": "uuid-abc", "module": "uuid-def"}}
        payload = {"custom_fields": {"severity": "high", "module": "banking"}}
        result = _build_custom_fields(payload, config)
        assert {"id": "uuid-abc", "value": "high"} in result
        assert {"id": "uuid-def", "value": "banking"} in result

    def test_unmapped_fields_use_label_as_id(self):
        """Agent field with no config map entry falls back to label as id."""
        payload = {"custom_fields": {"severity": "high"}}
        result = _build_custom_fields(payload, {})
        assert result == [{"id": "severity", "value": "high"}]


# -- handler.run ------------------------------------------------------------


class TestHandlerRun:
    def test_no_args_returns_error(self):
        result = run([], {})
        assert result["ok"] is False
        assert "No ticket payload" in result["error"]

    def test_invalid_json_returns_error(self):
        result = run(["not json"], {})
        assert result["ok"] is False
        assert "Invalid ticket payload" in result["error"]

    def test_no_key_returns_error(self):
        payload = json.dumps({"title": "Bug", "type": "bug", "category": "banking"})
        with patch("skills.clickup_ticket.handler._read_clickup_key", return_value=None):
            result = run([payload], {})
        assert result["ok"] is False
        assert "keyring" in result["error"]

    def test_no_list_id_returns_error(self):
        payload = json.dumps({"title": "Bug", "type": "bug", "category": "banking"})
        with patch("skills.clickup_ticket.handler._read_clickup_key", return_value="pk_test"):
            result = run([payload], {"default_list_id": ""})
        assert result["ok"] is False
        assert "No ClickUp list" in result["error"]

    def test_full_flow_success(self):
        payload = json.dumps({
            "title": "Transfer broken",
            "type": "bug",
            "category": "banking",
            "description": "The transfer button does nothing",
            "reproduction_steps": "1. Click transfer",
            "expected": "Modal opens",
            "actual": "Nothing happens",
            "environment": "Chrome 120",
            "feature": "transfer",
            "filed_by": "johnny",
        })

        hub_call_fn = MagicMock()
        hub_call_fn.side_effect = [
            {"found": True, "source": "mock", "summary": "Transfers move funds"},
            {"notified": True, "channel": "tech"},
        ]

        mock_task_response = MagicMock()
        mock_task_response.status_code = 200
        mock_task_response.json.return_value = {
            "id": "task999",
            "url": "https://app.clickup.com/t/123/task999",
        }

        with (
            patch("skills.clickup_ticket.handler._read_clickup_key", return_value="pk_test"),
            patch("httpx.post", return_value=mock_task_response),
        ):
            result = run([payload], {
                "hub_call_fn": hub_call_fn,
                "list_map": {"banking": "list123"},
                "default_assignees": [111],
                "clickup_team_id": "team456",
            })

        assert result["ok"] is True
        assert result["ticket_id"] == "task999"
        assert result["url"] == "https://app.clickup.com/t/123/task999"
        assert result["type"] == "bug"
        assert result["category"] == "banking"
        assert result["notified"] is True
        assert result["verify_result"]["found"] is True

        # hub was called twice: verify_behavior + tickets.notify
        assert hub_call_fn.call_count == 2
        first_call = hub_call_fn.call_args_list[0]
        assert first_call.args[0] == "kideconomy.verify_behavior"
        assert first_call.args[1]["feature"] == "transfer"
        second_call = hub_call_fn.call_args_list[1]
        assert second_call.args[0] == "tickets.notify"
        assert second_call.args[1]["ticket_id"] == "task999"

    def test_fetches_routing_from_hub_when_not_local(self):
        """When list_map is not in local config, handler calls tickets.meta on the hub."""
        payload = json.dumps({
            "title": "Transfer broken",
            "type": "bug",
            "category": "banking",
            "feature": "transfer",
            "filed_by": "johnny",
        })

        hub_call_fn = MagicMock()
        hub_call_fn.side_effect = [
            # tickets.meta call
            {
                "list_map": {"banking": "list_from_hub"},
                "default_list_id": "fallback_hub",
                "default_assignees": [222],
                "custom_field_map": {},
                "team_id": "team_from_hub",
            },
            # kideconomy.verify_behavior call
            {"found": False, "source": "mock"},
            # tickets.notify call
            {"notified": True, "channel": "tech"},
        ]

        mock_task_response = MagicMock()
        mock_task_response.status_code = 200
        mock_task_response.json.return_value = {
            "id": "hub_task",
            "url": "https://app.clickup.com/t/123/hub_task",
        }

        with (
            patch("skills.clickup_ticket.handler._read_clickup_key", return_value="pk_test"),
            patch("httpx.post", return_value=mock_task_response) as mock_post,
        ):
            result = run([payload], {"hub_call_fn": hub_call_fn})

        assert result["ok"] is True
        assert result["ticket_id"] == "hub_task"
        # tickets.meta was called first
        assert hub_call_fn.call_args_list[0].args[0] == "tickets.meta"
        # The task was posted to the list from the hub config
        post_url = mock_post.call_args.args[0]
        assert "list_from_hub" in post_url

    def test_invalid_type_defaults_to_bug(self):
        payload = json.dumps({"title": "X", "type": "nonsense", "category": "banking"})
        with patch("skills.clickup_ticket.handler._read_clickup_key", return_value=None):
            result = run([payload], {})
        assert result["ok"] is False
