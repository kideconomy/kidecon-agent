"""Lexor legal MCP client — read-only, staff-only, off-hub.

Connects the agent directly to the Lexor legal engineering platform via HTTP.
The hub is NOT a proxy for Lexor; this client makes the call itself using a
per-agent JWT held in the OS keyring.

Three-layer staff-only enforcement:
  1. Provisioning: only staff agents have ``api_key_lexor`` in the keyring.
  2. Capability cap: the JWT carries the ``legal`` role, which the Lexor
     server enforces as read-only (no draft/register/trigger tools).
  3. Local tier gate: ``call()`` refuses unless ``agent_hub_tier >= min_hub_tier``.

All errors return transparent three-part messages (what happened / why / what
to do next) instead of raising, so a Lexor failure never breaks a user-facing
turn.
"""

import logging

import httpx

from wrappers.keys import KEYRING_SERVICE
from wrappers.keys import api_key

logger = logging.getLogger(__name__)

KEYRING_KEY = api_key("lexor")

# Curated read-only allowlist. These are the ``legal``-role tools from
# docs/MCP_INTEGRATION.md. blueprint.plan is intentionally excluded — it opens
# a PR/checklist and is therefore non-informational even though it reads.
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "blueprint.list",
        "blueprint.get",
        "term.normalize",
        "search.semantic",
        "compliance.report",
        "entity.list",
        "entity.get",
        "peer.list",
        "pattern.get",
        "epic.status",
        "taxonomy.search",
        "context.build",
    },
)

DEFAULT_TIMEOUT = 15.0
DEFAULT_MIN_HUB_TIER = 3


class LexorClient:
    """Read-only Lexor MCP client for the agent runtime.

    Constructed at boot only when ``lexor.enabled`` is true and a keyring JWT
    is present. When ``None`` is passed to ``CognitiveEngine``, Lexor is
    disabled and the agent behaves exactly as before.
    """

    def __init__(
        self,
        base_url: str,
        role: str = "legal",
        timeout: float = DEFAULT_TIMEOUT,
        min_hub_tier: int = DEFAULT_MIN_HUB_TIER,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.role = role
        self.timeout = timeout
        self.min_hub_tier = min_hub_tier
        # transport is injectable for tests (httpx.MockTransport).
        self._transport = transport
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, transport=self._transport)
        return self._client

    def available_tools(self) -> list[str]:
        """Return the curated read-only allowlist (sorted)."""
        return sorted(ALLOWED_TOOLS)

    def call(self, tool_id: str, params: dict, agent_hub_tier: int) -> dict:
        """Call a Lexor tool.

        Returns ``{"result": ..., "error": ...}``. Exactly one is non-None on
        success; on a block/failure, ``result`` is None and ``error`` carries
        a transparent three-part message string. Never raises.
        """
        if tool_id not in ALLOWED_TOOLS:
            return {
                "result": None,
                "error": self._block_msg(
                    f"Lexor tool '{tool_id}' is not in the informational allowlist.",
                    "Lexor is wired for read-only legal information only.",
                    "Ask about entity blueprints, legal terms, taxonomy, or entity lists instead.",
                ),
            }

        if agent_hub_tier < self.min_hub_tier:
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor lookup was blocked.",
                    f"Lexor is staff-only (your tier: {agent_hub_tier}).",
                    "Ask your administrator to request staff access.",
                ),
            }

        jwt = self._read_jwt()
        if jwt is None:
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor lookup was skipped.",
                    "No Lexor credential is configured for this agent.",
                    "Ask your administrator to provision a legal-role token via "
                    "`kidecon key add --name lexor --value <jwt>`.",
                ),
            }

        url = f"{self.base_url}/api/v1/mcp/tools/{tool_id}"
        headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
        client = self._get_client()

        try:
            response = client.post(url, json=params, headers=headers)
        except httpx.TimeoutException:
            logger.warning("Lexor call timed out (tool=%s)", tool_id)
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor lookup failed.",
                    "The Lexor server did not respond in time.",
                    "Answering without Lexor context; retry later.",
                ),
            }
        except httpx.RequestError:
            logger.exception("Lexor call network error (tool=%s)", tool_id)
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor lookup failed.",
                    "Could not reach the Lexor server.",
                    "Answering without Lexor context; check the Lexor base_url.",
                ),
            }

        status = response.status_code
        if status == 401:
            logger.warning("Lexor 401 (tool=%s) — token expired/revoked", tool_id)
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor lookup failed.",
                    "The Lexor token is expired or revoked.",
                    "Ask the Lexor admin to re-issue a legal-role token.",
                ),
            }
        if status == 403:
            logger.warning("Lexor 403 (tool=%s) — role lacks tool", tool_id)
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor lookup failed.",
                    f"Your token's role ({self.role}) doesn't include that tool.",
                    "Informational lookups only are supported.",
                ),
            }
        if 400 <= status < 500:
            logger.warning("Lexor %d (tool=%s) — client error", status, tool_id)
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor rejected the input.",
                    f"The Lexor server returned HTTP {status} for '{tool_id}'.",
                    "Check the tool's required fields and retry.",
                ),
            }
        if status >= 500:
            logger.warning("Lexor %d (tool=%s) — server error", status, tool_id)
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor lookup failed.",
                    f"The Lexor server returned HTTP {status}.",
                    "Answering without Lexor context; retry later.",
                ),
            }

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Lexor returned non-JSON (tool=%s)", tool_id)
            return {
                "result": None,
                "error": self._block_msg(
                    "Lexor lookup failed.",
                    "The Lexor server returned an unparseable response.",
                    "Answering without Lexor context; retry later.",
                ),
            }

        logger.info("Lexor call ok (tool=%s, status=%d)", tool_id, status)
        return {"result": payload, "error": None}

    def _read_jwt(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, KEYRING_KEY)
        except Exception:
            logger.exception("keyring lookup for Lexor JWT failed")
            return None

    @staticmethod
    def _block_msg(what: str, why: str, next_step: str) -> str:
        return f"{what} Reason: {why} To proceed: {next_step}"


def build_lexor_client(config: dict) -> LexorClient | None:
    """Construct a LexorClient from agent config, or None when disabled.

    Enabled only when ``config["lexor"]["enabled"]`` is true AND a keyring
    JWT is present. Returns None otherwise so the runtime can pass None to
    CognitiveEngine and disable Lexor with zero behavior change.

    ``min_hub_tier`` is clamped to >= 3 (staff-only) to prevent an operator
    from silently weakening the staff-only gate via local config. An override
    below 3 produces a loud warning but is still rejected.
    """
    lexor_config = config.get("lexor") or {}
    if not lexor_config.get("enabled", False):
        return None

    base_url = lexor_config.get("base_url", "")
    if not base_url:
        logger.warning("Lexor enabled but base_url is empty — disabling")
        return None

    min_hub_tier = int(lexor_config.get("min_hub_tier", DEFAULT_MIN_HUB_TIER))
    if min_hub_tier < DEFAULT_MIN_HUB_TIER:
        logger.warning(
            "Lexor min_hub_tier=%d is below the staff-only floor (%d) — "
            "clamping to %d. Lexor is staff-only by design.",
            min_hub_tier,
            DEFAULT_MIN_HUB_TIER,
            DEFAULT_MIN_HUB_TIER,
        )
        min_hub_tier = DEFAULT_MIN_HUB_TIER

    client = LexorClient(
        base_url=base_url,
        role=lexor_config.get("role", "legal"),
        timeout=float(lexor_config.get("timeout", DEFAULT_TIMEOUT)),
        min_hub_tier=min_hub_tier,
    )

    if client._read_jwt() is None:
        logger.warning(
            "Lexor enabled but no api_key_lexor in keyring — run "
            "`kidecon key add --name lexor --value <jwt>`. Disabling until provisioned.",
        )
        return None

    logger.info(
        "Lexor client ready (base_url=%s, role=%s, tools=%d)",
        base_url,
        client.role,
        len(ALLOWED_TOOLS),
    )
    return client
