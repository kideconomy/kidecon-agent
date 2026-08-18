import logging
import uuid
from typing import TYPE_CHECKING

import httpx

from wrappers._http import hub_detail
from wrappers.keys import KEY_AGENT_ID
from wrappers.keys import KEY_JWT
from wrappers.keys import KEY_KE_TOKEN
from wrappers.keys import KEY_KE_USERNAME
from wrappers.keys import KEY_USER_JWT
from wrappers.keys import KEYRING_SERVICE
from wrappers.keys import get as keyring_get
from wrappers.keys import set_ as keyring_set

if TYPE_CHECKING:
    from wrappers.profile_store import Profile

logger = logging.getLogger(__name__)


class HubClient:
    def __init__(
        self,
        hub_url: str = "http://localhost:8000",
        kideconomy_api_url: str = "",
        profile: "Profile | None" = None,
        user_jwt: str | None = None,
    ):
        self.hub_url = hub_url.rstrip("/")
        self.kideconomy_api_url = kideconomy_api_url.rstrip("/")
        # Account-level USER JWT. When set (and no agent profile is attached),
        # account ops authenticate as the user without needing an agent. When
        # an explicit agent profile is attached (--agent), account ops keep
        # using the agent JWT for compatibility.
        self.user_jwt = user_jwt
        if profile:
            self.agent_id = profile.agent_id
            self.jwt = profile.jwt
            self._profile = profile
        elif user_jwt:
            # Account-only client: no agent identity is required or created.
            self.agent_id = None
            self.jwt = None
            self._profile = None
        else:
            self.agent_id = self._get_or_create_agent_id()
            self.jwt = self._get_jwt()
            self._profile = None

    def _get_or_create_agent_id(self) -> str:
        import keyring

        agent_id = keyring.get_password(KEYRING_SERVICE, KEY_AGENT_ID)
        if not agent_id:
            agent_id = str(uuid.uuid4())
            keyring.set_password(KEYRING_SERVICE, KEY_AGENT_ID, agent_id)
        return agent_id

    def _get_jwt(self) -> str | None:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEY_JWT)

    def fetch_ke_token(self, username: str, password: str) -> str:
        if not self.kideconomy_api_url:
            raise RuntimeError(
                "KidEconomy API URL not configured. Run 'kidecon init' first.",
            )
        response = httpx.post(
            f"{self.kideconomy_api_url}/api/auth-token/",
            json={"username": username, "password": password},
            timeout=15,
        )
        response.raise_for_status()
        token = response.json()["token"]
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEY_KE_USERNAME, username)
        keyring.set_password(KEYRING_SERVICE, KEY_KE_TOKEN, token)
        if self._profile:
            self._profile.ke_username = username
            from wrappers.profile_store import save_profile

            save_profile(self._profile)
        return token

    def get_stored_ke_token(self) -> str | None:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEY_KE_TOKEN)

    def get_stored_ke_username(self) -> str | None:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEY_KE_USERNAME)

    def fetch_user_jwt(self, ke_token: str) -> str:
        """Mint a USER JWT from the hub using a verified KidEconomy DRF token.

        POSTs to ``/api/user/token`` (which verifies the DRF token
        server-to-server and upserts the User), stores the returned USER JWT
        in the keyring under ``user_jwt``, and returns it. With this stored,
        ``status --me`` / ``status --refresh`` authenticate as the account
        without naming an agent.
        """
        if not ke_token:
            raise RuntimeError("No KidEconomy token — run `kidecon authenticate` first.")
        response = httpx.post(
            f"{self.hub_url}/api/user/token",
            json={"ke_token": ke_token},
            timeout=15,
        )
        if response.status_code == 401:
            raise RuntimeError("KidEconomy token rejected by the hub.") from None
        response.raise_for_status()
        token = response.json()["user_jwt"]
        keyring_set(KEY_USER_JWT, token)
        self.user_jwt = token
        return token

    @staticmethod
    def get_stored_user_jwt() -> str | None:
        """Read the stored account USER JWT from the keyring (None if unset)."""
        return keyring_get(KEY_USER_JWT)

    def register(
        self,
        name: str,
        ke_token: str | None = None,
        discord_user_id: str | None = None,
        platform: str = "cli",
        role: str = "standalone",
    ) -> str:
        payload: dict = {"agent_id": self.agent_id, "name": name, "platform": platform, "role": role}
        if ke_token:
            payload["ke_token"] = ke_token
        if discord_user_id:
            payload["discord_user_id"] = discord_user_id

        response = httpx.post(
            f"{self.hub_url}/api/register_agent",
            json=payload,
            timeout=15,
        )
        if response.status_code == 409:
            raise RuntimeError(
                "Agent name already registered with a different agent ID. "
                "This happens when `kidecon init` generated a new agent_id. "
                "Either delete the existing agent from the hub or restore "
                "the original agent_id in your keyring."
            ) from None
        if response.status_code == 403:
            detail = hub_detail(
                response,
                "Agent has been deactivated or is linked to a different KidEconomy account.",
            )
            raise RuntimeError(f"Registration rejected: {detail}") from None
        if response.status_code == 401:
            raise RuntimeError("KidEconomy token rejected by the hub.") from None
        response.raise_for_status()
        data = response.json()
        self.jwt = data["jwt"]
        if self._profile:
            self._profile.jwt = self.jwt
            from wrappers.profile_store import save_profile

            save_profile(self._profile)
        else:
            import keyring

            keyring.set_password(KEYRING_SERVICE, KEY_JWT, self.jwt)
        return self.jwt

    def _auth_headers(self) -> dict:
        if not self.jwt:
            raise RuntimeError(
                "Not registered. Run `kidecon authenticate` then `kidecon agents create` first."
            )
        return {"Authorization": f"Bearer {self.jwt}"}

    def _account_auth_headers(self) -> dict:
        """Auth headers for account ops (``/api/user/me`` / ``/api/user/refresh``).

        Prefers the account USER JWT when no agent profile is attached (the
        ``--agent``-less path); otherwise uses the agent JWT so an explicit
        ``--agent`` keeps agent-JWT behavior for compatibility.
        """
        if not self._profile and self.user_jwt:
            return {"Authorization": f"Bearer {self.user_jwt}"}
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}"}
        raise RuntimeError(
            "Not authenticated. Run `kidecon authenticate` first "
            "(then `kidecon agents create` for agent-scoped commands).",
        )

    def hub_call(self, tool_name: str, params: dict) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/mcp/call",
            json={"tool_name": tool_name, "params": params},
            headers=self._auth_headers(),
        )
        if response.status_code == 403:
            detail = hub_detail(
                response,
                "Access denied for this tool.",
            )
            raise RuntimeError(f"Tool '{tool_name}' rejected by hub: {detail}") from None
        if response.status_code == 401:
            raise RuntimeError(
                "Not authorized — JWT may be expired."
            ) from None
        response.raise_for_status()
        return response.json()

    def poll_messages(self, wait: int = 30) -> list[dict]:
        response = httpx.get(
            f"{self.hub_url}/api/messages/poll",
            params={"wait": wait} if wait else None,
            headers=self._auth_headers(),
            timeout=wait + 10.0 if wait else 10.0,
        )
        response.raise_for_status()
        return response.json().get("messages", [])

    def discover_manifest(self) -> list[dict]:
        """Fetch the MCP tool manifest from the hub."""
        response = httpx.get(
            f"{self.hub_url}/api/mcp/manifest",
            headers=self._auth_headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json().get("tools", [])

    def respond_to_message(
        self,
        message_id: str,
        accepted: bool,
        result: dict | None = None,
        reason: str | None = None,
    ) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/messages/{message_id}/respond",
            json={"accepted": accepted, "result": result, "reason": reason},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def send_message(
        self,
        to_agent_id: str,
        msg_type: str,
        payload: dict,
        reply_to: str | None = None,
    ) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/messages/send",
            json={
                "to_agent_id": to_agent_id,
                "type": msg_type,
                "payload": payload,
                "reply_to": reply_to,
            },
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def chat(self, text: str) -> str:
        """Post a CLI chat message to this agent and return its message_id."""
        response = httpx.post(
            f"{self.hub_url}/api/messages/chat",
            json={"text": text},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return str(response.json()["message_id"])

    def get_message(self, message_id: str) -> dict:
        """Fetch one message (status + result) addressed to this agent."""
        response = httpx.get(
            f"{self.hub_url}/api/messages/{message_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def publish_skill(self, skill_card: dict) -> dict:
        return self.submit_skill(
            name=skill_card["name"],
            version=skill_card.get("version", "1.0.0"),
            category=skill_card.get("category", "unknown"),
            description=skill_card.get("description", ""),
            definition=skill_card.get("definition"),
            config=skill_card.get("config"),
        )

    def discover_skills(self, query: str, vector: bool = False) -> list[dict]:
        params: dict = {"q": query}
        if vector:
            params["vector"] = "true"
        response = httpx.get(
            f"{self.hub_url}/api/skills/discover",
            params=params,
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("skills", [])

    def get_skill(self, skill_id: str) -> dict | None:
        """Fetch a single skill definition by ID."""
        response = httpx.get(
            f"{self.hub_url}/api/skills/{skill_id}",
            headers=self._auth_headers(),
            timeout=10.0,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_tier(self) -> int:
        return self.get_agent_profile(self.agent_id).get("tier", 1)

    def get_agent_profile(self, agent_id: str) -> dict:
        response = httpx.get(
            f"{self.hub_url}/api/agent/{agent_id}",
            headers=self._auth_headers(),
        )
        if response.status_code == 403:
            detail = hub_detail(
                response,
                "Access blocked — this agent or its KidEconomy account has been disabled.",
            )
            raise RuntimeError(f"Profile fetch rejected by hub: {detail}") from None
        if response.status_code == 401:
            raise RuntimeError(
                "Not authorized — JWT may be expired."
            ) from None
        response.raise_for_status()
        return response.json()

    def update_status(self, status: str) -> dict:
        response = httpx.put(
            f"{self.hub_url}/api/agent/{self.agent_id}/status",
            json={"status": status},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def get_user_me(self) -> dict:
        """Fetch the current KE user's account profile (incl. Discord link).

        ``discord_user_id`` here is the authoritative "is Discord set up"
        signal on the hub — the user owns the handle, not the agent.
        Authenticates with the stored USER JWT when no agent is named, else
        the agent JWT (compat).
        """
        response = httpx.get(
            f"{self.hub_url}/api/user/me",
            headers=self._account_auth_headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()

    def refresh_user(self) -> dict:
        """Re-verify this user against KidEconomy and pull fresh profile data.

        Returns the hub ``{"profile": ..., "refreshed": bool, "detail": ...}``
        payload so the caller can report whether KE supplied new data.
        Authenticates with the stored USER JWT when no agent is named, else
        the agent JWT (compat).
        """
        response = httpx.post(
            f"{self.hub_url}/api/user/refresh",
            headers=self._account_auth_headers(),
            timeout=15.0,
        )
        response.raise_for_status()
        return response.json()

    def admin_pending_skills(self) -> list[dict]:
        response = httpx.get(
            f"{self.hub_url}/api/admin/pending_skills",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("skills", [])

    def admin_approve_skill(self, skill_id: str) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/approve_skill/{skill_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_reject_skill(self, skill_id: str, reason: str) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/reject_skill/{skill_id}",
            json={"reason": reason},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_embed_all_skills(self) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/skills/embed_all",
            headers=self._auth_headers(),
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()

    def admin_set_skill_tier(self, skill_id: str, min_hub_tier: int) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/skills/{skill_id}/set_tier",
            json={"min_hub_tier": min_hub_tier},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_block_skill(self, skill_id: str) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/skills/{skill_id}/block",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_unblock_skill(self, skill_id: str) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/skills/{skill_id}/unblock",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_delete_skill(self, skill_id: str) -> dict:
        response = httpx.delete(
            f"{self.hub_url}/api/admin/skills/{skill_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_list_agents(self) -> list[dict]:
        response = httpx.get(
            f"{self.hub_url}/api/admin/agents",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("agents", [])

    def admin_set_tier(self, agent_id: str, tier: int) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/agents/{agent_id}/tier",
            json={"tier": tier},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_set_staff(self, agent_id: str, is_staff: bool) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/agents/{agent_id}/staff",
            json={"is_staff": is_staff},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_delete_agent(self, agent_id: str) -> dict:
        response = httpx.delete(
            f"{self.hub_url}/api/admin/agents/{agent_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_list_users(self) -> list[dict]:
        response = httpx.get(
            f"{self.hub_url}/api/admin/users",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("users", [])

    def admin_ban_user(self, username: str, reason: str | None = None) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/ban_user/{username}",
            json={"reason": reason},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def admin_unban_user(self, username: str) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/admin/users/{username}/unban",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def submit_skill(
        self,
        name: str,
        version: str,
        category: str,
        description: str,
        definition: dict | None = None,
        config: dict | None = None,
    ) -> dict:
        payload: dict = {
            "name": name,
            "version": version,
            "category": category,
            "description": description,
            "definition": definition or {},
        }
        if config is not None:
            payload["config"] = config
        response = httpx.post(
            f"{self.hub_url}/api/skills",
            json=payload,
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def my_skills(self, status: str | None = None) -> list[dict]:
        params = {}
        if status:
            params["status"] = status
        response = httpx.get(
            f"{self.hub_url}/api/skills/mine",
            params=params,
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("skills", [])

    def push_lesson(
        self,
        kind: str,
        title: str,
        summary: dict,
        tags: list[str] | None = None,
        domain_id: str | None = None,
        action_id: str | None = None,
    ) -> dict:
        """Push an agent-authored lesson to the hub knowledge store.

        POST /api/lessons with JWT auth. Expects {lesson_id, status} back.
        The caller must PII-scrub the payload first (edge deterministic regex,
        section 8.1) and wrap this call in try/except so a failed push never
        breaks a user-facing turn.
        """
        payload: dict = {
            "kind": kind,
            "title": title,
            "summary": summary,
            "tags": tags or [],
        }
        if domain_id:
            payload["domain_id"] = domain_id
        if action_id:
            payload["action_id"] = action_id
        response = httpx.post(
            f"{self.hub_url}/api/lessons",
            json=payload,
            headers=self._auth_headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def pull_my_lessons(
        self,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Fetch lessons owned by this agent's KidEconomy user.

        Lessons are user-scoped on the hub, so they are shared across all
        agents registered under the same KidEconomy account — an agent can
        be dropped without losing the user's lesson history.
        """
        params: dict = {"limit": limit}
        if status:
            params["status"] = status
        if kind:
            params["kind"] = kind
        response = httpx.get(
            f"{self.hub_url}/api/lessons/mine",
            params=params,
            headers=self._auth_headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get("lessons", [])
