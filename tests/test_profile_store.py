import logging
from contextlib import ExitStack
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from wrappers.profile_store import Profile
from wrappers.profile_store import create_profile
from wrappers.profile_store import rotate_jwt

logger = logging.getLogger(__name__)


def _mock_post_response(status_code: int, body: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    if body is not None:
        response.json.return_value = body
    else:
        response.json.side_effect = ValueError("no body")
    return response


def _profile():
    return Profile(
        agent_id="550e8400-e29b-41d4-a716-446655440000",
        name="my-agent",
        jwt="old-jwt",
        role="standalone",
    )


class TestRotateJwtErrorMapping:
    def test_403_ownership_mismatch_surfaces_real_detail(self):
        detail = (
            "This agent is already linked to another KidEconomy user and "
            "cannot be re-registered by a different account."
        )
        with patch("wrappers.profile_store.httpx.post") as mock_post, patch(
            "wrappers.profile_store.save_profile"
        ):
            mock_post.return_value = _mock_post_response(403, {"detail": detail})
            with pytest.raises(RuntimeError, match="linked to another KidEconomy user"):
                rotate_jwt(_profile(), "http://localhost:8000", "ke-token")

    def test_403_deactivation_surfaces_real_detail(self):
        with patch("wrappers.profile_store.httpx.post") as mock_post, patch(
            "wrappers.profile_store.save_profile"
        ):
            mock_post.return_value = _mock_post_response(403, {"detail": "Agent has been deactivated."})
            with pytest.raises(RuntimeError, match="deactivated"):
                rotate_jwt(_profile(), "http://localhost:8000", "ke-token")

    def test_401_surfaces_clean_message(self):
        with patch("wrappers.profile_store.httpx.post") as mock_post, patch(
            "wrappers.profile_store.save_profile"
        ):
            mock_post.return_value = _mock_post_response(401, {"detail": "bad"})
            with pytest.raises(RuntimeError, match="KidEconomy token rejected"):
                rotate_jwt(_profile(), "http://localhost:8000", "ke-token")

    def test_success_updates_jwt(self):
        with patch("wrappers.profile_store.httpx.post") as mock_post, patch(
            "wrappers.profile_store.save_profile"
        ) as mock_save:
            mock_post.return_value = _mock_post_response(200, {"jwt": "fresh-jwt"})
            profile = _profile()
            new_jwt = rotate_jwt(profile, "http://localhost:8000", "ke-token")
        assert new_jwt == "fresh-jwt"
        assert profile.jwt == "fresh-jwt"
        mock_save.assert_called_once_with(profile)


class TestCreateProfileErrorMapping:
    def _run(self, response, expect_match):
        with ExitStack() as stack:
            stack.enter_context(patch("wrappers.profile_store.httpx.post", return_value=response))
            stack.enter_context(patch("wrappers.profile_store.load_profile", return_value=None))
            stack.enter_context(patch("wrappers.profile_store.save_profile"))
            stack.enter_context(patch("wrappers.profile_store.set_active"))
            stack.enter_context(patch("wrappers.profile_store._ensure_dirs"))
            with pytest.raises(RuntimeError, match=expect_match):
                create_profile(
                    name="my-agent",
                    hub_url="http://localhost:8000",
                    ke_token="ke-token",
                )

    def test_403_ownership_mismatch_surfaces_real_detail(self):
        detail = (
            "This agent is already linked to another KidEconomy user and "
            "cannot be re-registered by a different account."
        )
        self._run(_mock_post_response(403, {"detail": detail}), "linked to another KidEconomy user")

    def test_403_deactivation_surfaces_real_detail(self):
        self._run(_mock_post_response(403, {"detail": "Agent has been deactivated."}), "deactivated")

    def test_401_surfaces_clean_message(self):
        self._run(_mock_post_response(401, {"detail": "bad"}), "KidEconomy token rejected")

    def test_409_surfaces_name_taken(self):
        self._run(_mock_post_response(409, {"detail": "Name already taken"}), "already registered")

    def test_409_non_json_body_uses_fallback(self):
        self._run(_mock_post_response(409, None), "already registered")
