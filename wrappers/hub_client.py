import logging
import uuid

import httpx
import keyring

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "kidecon-agent"
KEY_JWT = "hub_jwt"
KEY_AGENT_ID = "agent_id"
KEY_KE_USERNAME = "kideconomy_username"


class HubClient:
    def __init__(
        self,
        hub_url: str = "http://localhost:8000",
        kideconomy_api_url: str = "",
    ):
        self.hub_url = hub_url.rstrip("/")
        self.kideconomy_api_url = kideconomy_api_url.rstrip("/")
        self.agent_id = self._get_or_create_agent_id()
        self.jwt = self._get_jwt()

    def _get_or_create_agent_id(self) -> str:
        agent_id = keyring.get_password(KEYRING_SERVICE, KEY_AGENT_ID)
        if not agent_id:
            agent_id = str(uuid.uuid4())
            keyring.set_password(KEYRING_SERVICE, KEY_AGENT_ID, agent_id)
        return agent_id

    def _get_jwt(self) -> str | None:
        return keyring.get_password(KEYRING_SERVICE, KEY_JWT)

    def fetch_ke_token(self, username: str, password: str) -> str:
        """Authenticate against KidEconomy and return a DRF token.

        The password is used here and discarded — never stored.
        """
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
        keyring.set_password(KEYRING_SERVICE, KEY_KE_USERNAME, username)
        return token

    def register(
        self,
        name: str,
        ke_token: str | None = None,
        discord_user_id: str | None = None,
        platform: str = "cli",
    ) -> str:
        payload: dict = {"agent_id": self.agent_id, "name": name, "platform": platform}
        if ke_token:
            payload["ke_token"] = ke_token
        if discord_user_id:
            payload["discord_user_id"] = discord_user_id

        response = httpx.post(
            f"{self.hub_url}/api/register_agent",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        self.jwt = data["jwt"]
        keyring.set_password(KEYRING_SERVICE, KEY_JWT, self.jwt)
        return self.jwt

    def _auth_headers(self) -> dict:
        if not self.jwt:
            raise RuntimeError("Not registered. Run `kidecon setup` first.")
        return {"Authorization": f"Bearer {self.jwt}"}

    def hub_call(self, tool_name: str, params: dict) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/mcp/call",
            json={"tool_name": tool_name, "params": params},
            headers=self._auth_headers(),
        )
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

    def publish_skill(self, skill_card: dict) -> dict:
        return self.submit_skill(
            name=skill_card["name"],
            version=skill_card.get("version", "1.0.0"),
            category=skill_card.get("category", "unknown"),
            description=skill_card.get("description", ""),
            definition=skill_card.get("definition"),
        )

    def discover_skills(self, query: str) -> list[dict]:
        response = httpx.get(
            f"{self.hub_url}/api/skills/discover",
            params={"q": query},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("skills", [])

    def get_tier(self) -> int:
        response = httpx.get(
            f"{self.hub_url}/api/agent/{self.agent_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("tier", 1)

    def update_status(self, status: str) -> dict:
        response = httpx.put(
            f"{self.hub_url}/api/agent/{self.agent_id}/status",
            json={"status": status},
            headers=self._auth_headers(),
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

    def submit_skill(
        self,
        name: str,
        version: str,
        category: str,
        description: str,
        definition: dict | None = None,
    ) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/skills",
            json={
                "name": name,
                "version": version,
                "category": category,
                "description": description,
                "definition": definition or {},
            },
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
