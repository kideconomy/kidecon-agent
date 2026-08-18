import logging
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

logger = logging.getLogger(__name__)


def _mock_client():
    client = MagicMock()
    client.admin_delete_agent.return_value = {
        "agent_id": "test-id-123",
        "name": "to-delete",
        "deleted": True,
    }
    return client


def _mock_agent_profile():
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "test-agent",
        "tier": 2,
        "is_staff": False,
        "status": "online",
        "role": "standalone",
        "last_seen": "2026-01-15T12:00:00",
        "registered_at": "2026-01-01T08:00:00",
    }


def test_admin_delete_agent_calls_hub():
    client = _mock_client()
    result = client.admin_delete_agent("test-id-123")
    assert result["deleted"] is True
    assert result["name"] == "to-delete"
    client.admin_delete_agent.assert_called_once_with("test-id-123")


def test_admin_delete_agent_raises_on_error():
    client = MagicMock()
    client.admin_delete_agent.side_effect = Exception("404 Not Found")
    with pytest.raises(Exception, match="404"):
        client.admin_delete_agent("nonexistent-id")


def test_get_agent_profile_returns_full_profile():
    from wrappers.hub_client import HubClient

    with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer test"}):
        with patch("wrappers.hub_client.httpx.get") as mock_get:
            mock_get.return_value.raise_for_status = MagicMock()
            mock_get.return_value.json.return_value = _mock_agent_profile()

            client = HubClient(hub_url="http://localhost:8000", profile=MagicMock())
            client.agent_id = "550e8400-e29b-41d4-a716-446655440000"
            client.jwt = "fake-jwt"

            result = client.get_agent_profile("550e8400-e29b-41d4-a716-446655440000")

    assert result["tier"] == 2
    assert result["is_staff"] is False
    assert result["role"] == "standalone"
    assert result["name"] == "test-agent"


def test_get_tier_passes_through_to_get_agent_profile():
    from wrappers.hub_client import HubClient

    profile = _mock_agent_profile()
    with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer test"}):
        with patch("wrappers.hub_client.httpx.get") as mock_get:
            mock_get.return_value.raise_for_status = MagicMock()
            mock_get.return_value.json.return_value = profile

            client = HubClient(hub_url="http://localhost:8000", profile=MagicMock())
            client.agent_id = "550e8400-e29b-41d4-a716-446655440000"
            client.jwt = "fake-jwt"

            tier = client.get_tier()

    assert tier == 2


def test_get_user_me_hits_hub_and_returns_discord():
    from wrappers.hub_client import HubClient

    body = {
        "id": "user-1",
        "ke_username": "johnny",
        "ke_user_id": None,
        "tier": 3,
        "is_staff": True,
        "is_active": True,
        "is_local_admin": False,
        "discord_user_id": "1234567890",
        "last_verified_at": None,
        "ke_disabled_at": None,
    }
    with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer test"}):
        with patch("wrappers.hub_client.httpx.get") as mock_get:
            mock_get.return_value.raise_for_status = MagicMock()
            mock_get.return_value.json.return_value = body
            client = HubClient(hub_url="http://localhost:8000", profile=MagicMock())
            client.jwt = "fake-jwt"
            result = client.get_user_me()

    assert result["discord_user_id"] == "1234567890"
    assert "api/user/me" in mock_get.call_args[0][0]


def test_refresh_user_hits_hub_and_reports_refreshed():
    from wrappers.hub_client import HubClient

    payload = {
        "profile": {"discord_user_id": "ABCDEF", "ke_username": "johnny"},
        "refreshed": True,
        "detail": None,
    }
    with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer test"}):
        with patch("wrappers.hub_client.httpx.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()
            mock_post.return_value.json.return_value = payload
            client = HubClient(hub_url="http://localhost:8000", profile=MagicMock())
            client.jwt = "fake-jwt"
            result = client.refresh_user()

    assert result["refreshed"] is True
    assert "api/user/refresh" in mock_post.call_args[0][0]


def _mock_post_response(status_code: int, body: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    if body is not None:
        response.json.return_value = body
    else:
        response.json.side_effect = ValueError("no body")
    return response


class TestRegister403Mapping:
    def _client(self):
        from wrappers.hub_client import HubClient

        client = HubClient(hub_url="http://localhost:8000")
        client.agent_id = "550e8400-e29b-41d4-a716-446655440000"
        client.jwt = None
        return client

    def test_403_ownership_mismatch_surfaces_real_detail(self):
        from wrappers.hub_client import HubClient

        mismatch_detail = (
            "This agent is already linked to another KidEconomy user and "
            "cannot be re-registered by a different account."
        )
        with patch.object(HubClient, "_auth_headers", return_value={}):
            with patch("wrappers.hub_client.httpx.post") as mock_post:
                mock_post.return_value = _mock_post_response(403, {"detail": mismatch_detail})
                client = self._client()
                with pytest.raises(RuntimeError, match="linked to another KidEconomy user"):
                    client.register(name="my-agent")

    def test_403_deactivation_surfaces_real_detail(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={}):
            with patch("wrappers.hub_client.httpx.post") as mock_post:
                mock_post.return_value = _mock_post_response(
                    403, {"detail": "Agent has been deactivated."}
                )
                client = self._client()
                with pytest.raises(RuntimeError, match="deactivated"):
                    client.register(name="my-agent")

    def test_403_non_json_body_uses_fallback(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={}):
            with patch("wrappers.hub_client.httpx.post") as mock_post:
                mock_post.return_value = _mock_post_response(403, None)
                client = self._client()
                with pytest.raises(RuntimeError, match="Registration rejected"):
                    client.register(name="my-agent")


class TestHubCall403:
    def test_403_raises_clean_runtime_error(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("wrappers.hub_client.httpx.post") as mock_post:
                mock_post.return_value = _mock_post_response(
                    403, {"detail": "Access denied for this tool."}
                )
                client = HubClient(hub_url="http://localhost:8000")
                client.jwt = "fake-jwt"
                with pytest.raises(RuntimeError, match="Access denied for this tool"):
                    client.hub_call("some_tool", {})

    def test_401_raises_clean_runtime_error(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("wrappers.hub_client.httpx.post") as mock_post:
                mock_post.return_value = _mock_post_response(401, {"detail": "bad token"})
                client = HubClient(hub_url="http://localhost:8000")
                client.jwt = "fake-jwt"
                with pytest.raises(RuntimeError, match="JWT may be expired"):
                    client.hub_call("some_tool", {})


class TestGetAgentProfileErrorMapping:
    def test_403_surfaces_real_detail(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("wrappers.hub_client.httpx.get") as mock_get:
                mock_get.return_value = _mock_post_response(
                    403, {"detail": "Agent has been deactivated."}
                )
                client = HubClient(hub_url="http://localhost:8000")
                client.jwt = "fake-jwt"
                with pytest.raises(RuntimeError, match="deactivated"):
                    client.get_agent_profile("550e8400-e29b-41d4-a716-446655440000")

    def test_401_surfaces_clean_message(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("wrappers.hub_client.httpx.get") as mock_get:
                mock_get.return_value = _mock_post_response(401, {"detail": "bad"})
                client = HubClient(hub_url="http://localhost:8000")
                client.jwt = "fake-jwt"
                with pytest.raises(RuntimeError, match="JWT may be expired"):
                    client.get_agent_profile("550e8400-e29b-41d4-a716-446655440000")


class TestAdminUserMethods:
    def test_admin_list_users(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("wrappers.hub_client.httpx.get") as mock_get:
                mock_get.return_value.raise_for_status = MagicMock()
                mock_get.return_value.json.return_value = {
                    "users": [
                        {"id": "u1", "ke_username": "alice", "tier": 1, "is_staff": False,
                         "is_active": True, "agent_count": 2}
                    ]
                }
                client = HubClient(hub_url="http://localhost:8000")
                client.jwt = "fake-jwt"
                result = client.admin_list_users()

        assert result[0]["ke_username"] == "alice"
        assert result[0]["agent_count"] == 2

    def test_admin_ban_user(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("wrappers.hub_client.httpx.post") as mock_post:
                mock_post.return_value = _mock_post_response(
                    200, {"kideconomy_user_id": "alice", "agents_deactivated": 2, "reason": "bad"}
                )
                client = HubClient(hub_url="http://localhost:8000")
                client.jwt = "fake-jwt"
                result = client.admin_ban_user("alice", reason="bad")

        assert result["agents_deactivated"] == 2
        mock_post.assert_called_once()

    def test_admin_unban_user(self):
        from wrappers.hub_client import HubClient

        with patch.object(HubClient, "_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("wrappers.hub_client.httpx.post") as mock_post:
                mock_post.return_value = _mock_post_response(
                    200, {"kideconomy_user_id": "alice", "is_active": True, "agents_reactivated": 2}
                )
                client = HubClient(hub_url="http://localhost:8000")
                client.jwt = "fake-jwt"
                result = client.admin_unban_user("alice")

        assert result["is_active"] is True
        assert result["agents_reactivated"] == 2
