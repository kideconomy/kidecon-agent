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
    monkeypatch.setattr(cli, "_account_client", lambda **kw: client)
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "johnny" in result.output
    assert "…7890" in result.output


def test_status_me_flag_same_as_default(monkeypatch):
    client = MagicMock()
    client.get_user_me.return_value = _me_payload(discord_user_id=None)
    monkeypatch.setattr(cli, "_account_client", lambda **kw: client)
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
    monkeypatch.setattr(cli, "_account_client", lambda **kw: client)
    result = runner.invoke(cli.app, ["status", "--refresh"])
    assert result.exit_code == 0
    assert "refreshed" in result.output
    assert "…CDEF" in result.output
    client.get_user_me.assert_not_called()


def test_status_agent_refresh_passes_agent(monkeypatch):
    seen = {}

    def fake_account_client(**kw):
        seen.update(kw)
        client = MagicMock()
        client.refresh_user.return_value = {
            "profile": _me_payload(discord_user_id="ABCDEF"),
            "refreshed": True,
            "detail": None,
        }
        return client

    monkeypatch.setattr(cli, "_account_client", fake_account_client)
    result = runner.invoke(cli.app, ["status", "--agent", "legal-johnny", "--refresh"])
    assert result.exit_code == 0
    assert seen.get("agent") == "legal-johnny"
    assert "refreshed" in result.output


def test_status_name_routes_to_agent(monkeypatch):
    recorded = {}
    monkeypatch.setattr(cli, "_status_agent", lambda name: recorded.setdefault("name", name))
    result = runner.invoke(cli.app, ["status", "--name", "legal-johnny"])
    assert result.exit_code == 0
    assert recorded.get("name") == "legal-johnny"


def test_status_multiple_profiles_shows_hint(monkeypatch):
    monkeypatch.setattr(cli, "_stored_user_jwt", lambda: None)
    monkeypatch.setattr(cli, "list_profiles", lambda: ["legal-johnny", "dm-johnny"])
    result = runner.invoke(cli.app, ["status", "--me"])
    assert result.exit_code == 1
    assert "legal-johnny" in result.output
    assert "dm-johnny" in result.output
    assert "--agent" in result.output


def test_status_no_profiles_hints_to_create(monkeypatch):
    monkeypatch.setattr(cli, "_stored_user_jwt", lambda: None)
    monkeypatch.setattr(cli, "list_profiles", list)
    result = runner.invoke(cli.app, ["status", "--me"])
    assert result.exit_code == 1
    assert "No agents set up" in result.output


def test_account_client_uses_user_jwt_and_skips_agent(monkeypatch):
    """A stored USER JWT lets the account view run with no --agent, even when
    several agent profiles exist (which would otherwise prompt to pick one)."""
    monkeypatch.setattr(cli, "_stored_user_jwt", lambda: "user-jwt-123")
    monkeypatch.setattr(cli, "load_config", lambda: {"hub_url": "http://hub", "kideconomy_api_url": ""})
    monkeypatch.setattr(cli, "list_profiles", lambda: ["legal-johnny", "dm-johnny"])
    client = cli._account_client()
    assert client.user_jwt == "user-jwt-123"
    assert client._profile is None
    assert client.jwt is None


def test_account_client_falls_back_to_agent_when_no_user_jwt(monkeypatch):
    """Without a USER JWT, the single-agent borrow fallback still works."""
    from unittest.mock import MagicMock

    monkeypatch.setattr(cli, "_stored_user_jwt", lambda: None)
    monkeypatch.setattr(cli, "load_config", lambda: {"hub_url": "http://hub", "kideconomy_api_url": ""})
    prof = MagicMock()
    prof.jwt = "agent-jwt"
    prof.name = "solo"
    monkeypatch.setattr(cli, "list_profiles", lambda: ["solo"])
    monkeypatch.setattr(cli, "resolve_profile", lambda n: prof)
    client = cli._account_client()
    assert client.jwt == "agent-jwt"
    assert client.user_jwt is None


def test_status_me_with_user_jwt_calls_get_user_me(monkeypatch):
    """``status --me`` authenticates with the USER JWT (no --agent) and calls
    the account endpoint — the core decoupling acceptance test."""
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get_user_me.return_value = _me_payload()
    monkeypatch.setattr(cli, "_account_client", lambda **kw: client)
    result = runner.invoke(cli.app, ["status", "--me"])
    assert result.exit_code == 0
    client.get_user_me.assert_called_once()
    assert "johnny" in result.output


def test_authenticate_mints_user_jwt_after_ke_login(monkeypatch):
    """`kidecon authenticate` stores the KE DRF token AND mints a USER JWT."""
    import getpass

    calls = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            calls["init"] = kwargs

        def fetch_ke_token(self, username, password):
            calls["ke"] = (username, password)
            return "drf-token"

        def fetch_user_jwt(self, ke_token):
            calls["user_jwt_arg"] = ke_token
            return "minted-user-jwt"

    monkeypatch.setattr(cli, "HubClient", FakeClient)
    monkeypatch.setattr(cli, "load_config", lambda: {"hub_url": "http://hub", "kideconomy_api_url": "http://ke"})
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "secret-pw")
    result = runner.invoke(cli.app, ["authenticate", "--ke-username", "johnny"])

    assert result.exit_code == 0
    assert calls.get("user_jwt_arg") == "drf-token"
    assert calls["ke"][0] == "johnny"
    assert "without --agent" in result.output
