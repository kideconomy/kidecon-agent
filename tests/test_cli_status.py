import logging
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cli import kidecon as cli

logger = logging.getLogger(__name__)

runner = CliRunner()


def _me_payload(**overrides):
    payload = {
        "ke_username": "johnny",
        "tier": 3,
        "is_staff": True,
        "is_active": True,
        "discord_user_id": "1234567890",
    }
    payload.update(overrides)
    return payload


def test_status_default_shows_me(monkeypatch):
    client = MagicMock()
    client.get_user_me.return_value = _me_payload()
    monkeypatch.setattr(cli, "_account_client", lambda: client)
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "johnny" in result.output
    assert "…7890" in result.output


def test_status_me_flag_same_as_default(monkeypatch):
    client = MagicMock()
    client.get_user_me.return_value = _me_payload(discord_user_id=None)
    monkeypatch.setattr(cli, "_account_client", lambda: client)
    result = runner.invoke(cli.app, ["status", "--me"])
    assert result.exit_code == 0
    assert "not linked" in result.output


def test_status_refresh_reports_refreshed(monkeypatch):
    client = MagicMock()
    client.refresh_user.return_value = {
        "profile": _me_payload(discord_user_id="ABCDEF"),
        "refreshed": True,
        "detail": None,
    }
    monkeypatch.setattr(cli, "_account_client", lambda: client)
    result = runner.invoke(cli.app, ["status", "--refresh"])
    assert result.exit_code == 0
    assert "refreshed" in result.output
    assert "…CDEF" in result.output
    client.get_user_me.assert_not_called()


def test_status_name_routes_to_agent(monkeypatch):
    recorded = {}
    monkeypatch.setattr(cli, "_status_agent", lambda name: recorded.setdefault("name", name))
    result = runner.invoke(cli.app, ["status", "--name", "legal-johnny"])
    assert result.exit_code == 0
    assert recorded.get("name") == "legal-johnny"


def test_status_multiple_profiles_shows_hint(monkeypatch):
    monkeypatch.setattr(cli, "list_profiles", lambda: ["legal-johnny", "dm-johnny"])
    result = runner.invoke(cli.app, ["status", "--me"])
    assert result.exit_code == 1
    assert "legal-johnny" in result.output
    assert "dm-johnny" in result.output
    assert "--agent" in result.output


def test_status_no_profiles_hints_to_create(monkeypatch):
    monkeypatch.setattr(cli, "list_profiles", lambda: [])
    result = runner.invoke(cli.app, ["status", "--me"])
    assert result.exit_code == 1
    assert "No agents set up" in result.output