import logging
import uuid

import httpx
import keyring

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "kidecon-agent"
KEY_JWT = "hub_jwt"
KEY_AGENT_ID = "agent_id"


class HubClient:
    def __init__(self, hub_url: str = "http://localhost:8000"):
        self.hub_url = hub_url.rstrip("/")
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

    def register(self, name: str, platform: str = "cli") -> str:
        response = httpx.post(
            f"{self.hub_url}/api/register_agent",
            json={"agent_id": self.agent_id, "name": name, "platform": platform},
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

    def poll_messages(self) -> list[dict]:
        response = httpx.get(
            f"{self.hub_url}/api/messages/poll",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("messages", [])

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

    def publish_skill(self, skill_card: dict) -> bool:
        # Stub — hub skill submission endpoint TBD
        logger.info("Publishing skill: %s", skill_card.get("name", "unknown"))
        return True

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
