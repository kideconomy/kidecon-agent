"""Tests for wrappers/lexor_client.py.

Covers: URL/header/body construction, the three-layer staff-only gate
(tier / provisioning / capability cap), HTTP error mapping to transparent
three-part messages, and the no-logs-of-secrets rule.
"""

import logging

import httpx

from wrappers.lexor_client import ALLOWED_TOOLS
from wrappers.lexor_client import DEFAULT_MIN_HUB_TIER
from wrappers.lexor_client import KEYRING_KEY
from wrappers.lexor_client import LexorClient
from wrappers.lexor_client import build_lexor_client

logger = logging.getLogger(__name__)


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _make_client(
    transport_handler=None,
    jwt="jwt-abc",
    role="legal",
    min_hub_tier=3,
    base_url="http://lexor.test:8000",
) -> LexorClient:
    transport = _mock_transport(transport_handler) if transport_handler else None
    client = LexorClient(
        base_url=base_url,
        role=role,
        min_hub_tier=min_hub_tier,
        transport=transport,
    )
    # Stub keyring so we don't touch the real OS keyring.
    client._read_jwt = lambda: jwt  # type: ignore[method-assign]
    return client


# ------------------------------------------------------------------
# success path
# ------------------------------------------------------------------
def test_call_success_posts_correct_url_headers_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"blueprints": ["pbc", "llc"]})

    client = _make_client(handler)
    resp = client.call("blueprint.list", {}, agent_hub_tier=3)

    assert captured["url"] == "http://lexor.test:8000/api/v1/mcp/tools/blueprint.list"
    assert captured["auth"] == "Bearer jwt-abc"
    assert captured["content_type"] == "application/json"
    assert captured["body"] == "{}"
    assert resp["error"] is None
    assert resp["result"] == {"blueprints": ["pbc", "llc"]}


def test_call_passes_params_as_json():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"ok": True})

    client = _make_client(handler)
    client.call("term.normalize", {"term": "PBC"}, agent_hub_tier=3)
    assert '"term"' in captured["body"]
    assert "PBC" in captured["body"]


# ------------------------------------------------------------------
# Layer 1: local tier gate (staff-only)
# ------------------------------------------------------------------
def test_call_blocked_for_non_staff_tier_no_http_made():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    client = _make_client(handler)
    resp = client.call("blueprint.list", {}, agent_hub_tier=1)

    assert resp["result"] is None
    assert "blocked" in resp["error"].lower()
    assert "staff-only" in resp["error"].lower()
    assert "your tier: 1" in resp["error"]
    assert calls == [], "no HTTP call should be made when tier gate blocks"


def test_call_blocked_for_tier_below_min():
    client = _make_client(lambda r: httpx.Response(200, json={}))
    resp = client.call("blueprint.list", {}, agent_hub_tier=2)
    assert resp["result"] is None
    assert "your tier: 2" in resp["error"]


# ------------------------------------------------------------------
# Layer 2: provisioning (no keyring credential)
# ------------------------------------------------------------------
def test_call_blocked_when_no_jwt_no_http_made(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    client = _make_client(handler, jwt=None)
    resp = client.call("blueprint.list", {}, agent_hub_tier=3)

    assert resp["result"] is None
    assert "skipped" in resp["error"].lower() or "no Lexor credential" in resp["error"]
    assert calls == [], "no HTTP call when JWT missing"


# ------------------------------------------------------------------
# Layer 3: capability cap — allowlist (write tools refused client-side)
# ------------------------------------------------------------------
def test_call_blocked_for_write_tool_outside_allowlist():
    client = _make_client(lambda r: httpx.Response(200, json={}))
    resp = client.call("architect.draft", {"type_id": "x"}, agent_hub_tier=3)
    assert resp["result"] is None
    assert "allowlist" in resp["error"].lower()
    assert "read-only" in resp["error"].lower()


def test_blueprint_plan_excluded_from_allowlist():
    assert "blueprint.plan" not in ALLOWED_TOOLS
    assert "blueprint.list" in ALLOWED_TOOLS
    assert "architect.draft" not in ALLOWED_TOOLS
    assert "entity.register" not in ALLOWED_TOOLS


def test_available_tools_returns_sorted_allowlist():
    client = _make_client(lambda r: httpx.Response(200, json={}))
    tools = client.available_tools()
    assert tools == sorted(ALLOWED_TOOLS)
    assert "blueprint.list" in tools


# ------------------------------------------------------------------
# HTTP error mapping (transparent three-part messages)
# ------------------------------------------------------------------
def test_call_401_maps_to_expired_token_message():
    client = _make_client(lambda r: httpx.Response(401, json={}))
    resp = client.call("blueprint.list", {}, agent_hub_tier=3)
    assert resp["result"] is None
    assert "expired or revoked" in resp["error"]


def test_call_403_maps_to_role_lacks_tool_message():
    client = _make_client(lambda r: httpx.Response(403, json={}))
    resp = client.call("blueprint.list", {}, agent_hub_tier=3)
    assert resp["result"] is None
    assert "role" in resp["error"].lower()
    assert "legal" in resp["error"]


def test_call_400_maps_to_client_error_message():
    client = _make_client(lambda r: httpx.Response(400, json={"detail": "bad"}))
    resp = client.call("term.normalize", {"term": "x"}, agent_hub_tier=3)
    assert resp["result"] is None
    assert "HTTP 400" in resp["error"]


def test_call_500_maps_to_server_error_message():
    client = _make_client(lambda r: httpx.Response(500, json={}))
    resp = client.call("blueprint.list", {}, agent_hub_tier=3)
    assert resp["result"] is None
    assert "HTTP 500" in resp["error"]


def test_call_timeout_maps_to_timeout_message():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = _make_client(handler)
    resp = client.call("blueprint.list", {}, agent_hub_tier=3)
    assert resp["result"] is None
    assert "did not respond" in resp["error"] or "time" in resp["error"].lower()


def test_call_network_error_maps_to_unreachable_message():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    client = _make_client(handler)
    resp = client.call("blueprint.list", {}, agent_hub_tier=3)
    assert resp["result"] is None
    assert "reach" in resp["error"].lower() or "network" in resp["error"].lower()


def test_call_non_json_response_maps_to_unparseable():
    client = _make_client(lambda r: httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"}))
    resp = client.call("blueprint.list", {}, agent_hub_tier=3)
    assert resp["result"] is None
    assert "unparseable" in resp["error"].lower() or "parse" in resp["error"].lower()


def test_call_never_raises_on_error():
    """All failure paths return a dict; none raise into the turn."""
    client = _make_client(lambda r: httpx.Response(503, json={}))
    for tool in ["blueprint.list", "term.normalize", "entity.get"]:
        resp = client.call(tool, {}, agent_hub_tier=3)
        assert isinstance(resp, dict)
        assert "error" in resp
        assert "result" in resp


# ------------------------------------------------------------------
# Secrets not logged
# ------------------------------------------------------------------
def test_jwt_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    client = _make_client(lambda r: httpx.Response(200, json={"ok": True}), jwt="super-secret-jwt-xyz")
    client.call("blueprint.list", {}, agent_hub_tier=3)
    assert "super-secret-jwt-xyz" not in caplog.text


def test_raw_params_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    client = _make_client(lambda r: httpx.Response(200, json={"ok": True}))
    client.call("term.normalize", {"term": "SECRET_TERM_VALUE"}, agent_hub_tier=3)
    assert "SECRET_TERM_VALUE" not in caplog.text


# ------------------------------------------------------------------
# build_lexor_client factory
# ------------------------------------------------------------------
def test_build_lexor_client_disabled_returns_none():
    assert build_lexor_client({}) is None
    assert build_lexor_client({"lexor": {"enabled": False}}) is None


def test_build_lexor_client_no_base_url_returns_none():
    assert build_lexor_client({"lexor": {"enabled": True, "base_url": ""}}) is None


def test_build_lexor_client_no_keyring_key_returns_none(monkeypatch):
    monkeypatch.setattr("keyring.get_password", lambda service, key: None)
    client = build_lexor_client({"lexor": {"enabled": True, "base_url": "http://x"}})
    assert client is None


def test_build_lexor_client_constructs_when_enabled_and_provisioned(monkeypatch):
    monkeypatch.setattr("keyring.get_password", lambda service, key: "jwt-here" if key == KEYRING_KEY else None)
    client = build_lexor_client(
        {"lexor": {"enabled": True, "base_url": "http://lexor.test:8000", "role": "legal", "timeout": 20}},
    )
    assert client is not None
    assert client.base_url == "http://lexor.test:8000"
    assert client.role == "legal"
    assert client.timeout == 20.0


def test_build_lexor_client_clamps_min_hub_tier_below_floor(monkeypatch):
    monkeypatch.setattr("keyring.get_password", lambda service, key: "jwt-here" if key == KEYRING_KEY else None)
    client = build_lexor_client(
        {"lexor": {"enabled": True, "base_url": "http://x", "min_hub_tier": 1}},
    )
    assert client is not None
    assert client.min_hub_tier == DEFAULT_MIN_HUB_TIER  # clamped to 3


def test_read_jwt_uses_keyring_service(monkeypatch):
    seen = {}

    def fake_get(service, key):
        seen["service"] = service
        seen["key"] = key
        return "jwt"

    monkeypatch.setattr("keyring.get_password", fake_get)
    client = LexorClient(base_url="http://x")
    assert client._read_jwt() == "jwt"
    assert seen["key"] == KEYRING_KEY
