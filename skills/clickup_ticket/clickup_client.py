"""Local ClickUp API client for the clickup-ticket skill.

Reads the user's ClickUp personal API token from the OS keyring (set via
`kidecon key add --name clickup --value pk_xxx`) and makes direct HTTP calls
to the ClickUp API. The token never leaves this process — it is not sent to
the hub, logged, or persisted to disk.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

CLICKUP_API = "https://api.clickup.com/api/v2"

PRIORITY_MAP = {
    "urgent": 1,
    "high": 2,
    "normal": 3,
    "low": 4,
}


class ClickUpError(Exception):
    """Raised when a ClickUp API call fails."""


class ClickUpClient:
    """Thin wrapper around the ClickUp API v2.

    The token is passed once at construction (read from keyring by the caller)
    and used for all subsequent calls.  No token is stored on this object
    beyond the instance lifetime.
    """

    def __init__(self, api_token: str, timeout: float = 15.0):
        if not api_token:
            raise ClickUpError("No ClickUp API token provided. Run: kidecon key add --name clickup --value <token>")
        self._token = api_token
        self._timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": self._token, "Content-Type": "application/json"}

    def get_user(self) -> dict:
        """Fetch the authenticated user's info — used to validate the token."""
        resp = httpx.get(f"{CLICKUP_API}/user", headers=self._headers(), timeout=self._timeout)
        if resp.status_code != 200:
            raise ClickUpError(f"ClickUp token validation failed (HTTP {resp.status_code})")
        return resp.json().get("user", {})

    def get_lists(self, folder_id: str) -> list[dict]:
        """List all lists in a folder."""
        resp = httpx.get(
            f"{CLICKUP_API}/folder/{folder_id}/list",
            headers=self._headers(),
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise ClickUpError(f"Failed to fetch lists from folder {folder_id} (HTTP {resp.status_code})")
        return resp.json().get("lists", [])

    def get_folders(self, space_id: str) -> list[dict]:
        """List all folders in a space."""
        resp = httpx.get(
            f"{CLICKUP_API}/space/{space_id}/folder",
            headers=self._headers(),
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise ClickUpError(f"Failed to fetch folders from space {space_id} (HTTP {resp.status_code})")
        return resp.json().get("folders", [])

    def get_spaces(self, team_id: str) -> list[dict]:
        """List all spaces in a team."""
        resp = httpx.get(
            f"{CLICKUP_API}/team/{team_id}/space",
            headers=self._headers(),
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise ClickUpError(f"Failed to fetch spaces for team {team_id} (HTTP {resp.status_code})")
        return resp.json().get("spaces", [])

    def get_teams(self) -> list[dict]:
        """List all teams the authenticated user belongs to."""
        resp = httpx.get(f"{CLICKUP_API}/team", headers=self._headers(), timeout=self._timeout)
        if resp.status_code != 200:
            raise ClickUpError(f"Failed to fetch teams (HTTP {resp.status_code})")
        return resp.json().get("teams", [])

    def create_task(
        self,
        list_id: str,
        name: str,
        description: str = "",
        *,
        tags: list[str] | None = None,
        priority: str = "normal",
        assignees: list[int] | None = None,
        custom_fields: list[dict] | None = None,
        due_date: int | None = None,
        notify_all: bool = True,
    ) -> dict:
        """Create a task in a ClickUp list.

        Returns the full task object from ClickUp, including ``id`` and ``url``.
        Raises ``ClickUpError`` on failure.
        """
        body: dict = {
            "name": name,
            "description": description,
            "notify_all": notify_all,
            "check_required_custom_fields": False,
        }
        if tags:
            body["tags"] = tags
        if priority and priority in PRIORITY_MAP:
            body["priority"] = PRIORITY_MAP[priority]
        if assignees:
            body["assignees"] = assignees
        if custom_fields:
            body["custom_fields"] = custom_fields
        if due_date:
            body["due_date"] = due_date

        resp = httpx.post(
            f"{CLICKUP_API}/list/{list_id}/task",
            json=body,
            headers=self._headers(),
            timeout=self._timeout,
        )
        if resp.status_code not in (200, 201):
            raise ClickUpError(f"Failed to create ClickUp task in list {list_id} (HTTP {resp.status_code}): {resp.text}")
        return resp.json()

    def get_task(self, task_id: str) -> dict:
        """Fetch a single task by ID."""
        resp = httpx.get(
            f"{CLICKUP_API}/task/{task_id}",
            headers=self._headers(),
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise ClickUpError(f"Failed to fetch task {task_id} (HTTP {resp.status_code})")
        return resp.json()


def build_task_url(team_id: str, task_id: str) -> str:
    """Construct the human-readable ClickUp task URL."""
    if team_id:
        return f"https://app.clickup.com/t{team_id}/{task_id}"
    return f"https://app.clickup.com/t/{task_id}"


def format_description(
    base_description: str = "",
    *,
    reproduction_steps: str = "",
    expected: str = "",
    actual: str = "",
    environment: str = "",
) -> str:
    """Build a well-structured markdown description for a ClickUp ticket."""
    sections: list[str] = []
    if base_description:
        sections.append(base_description)
    if reproduction_steps:
        sections.append(f"**Steps to reproduce**\n{reproduction_steps}")
    if expected:
        sections.append(f"**Expected**\n{expected}")
    if actual:
        sections.append(f"**Actual**\n{actual}")
    if environment:
        sections.append(f"**Environment**\n{environment}")
    return "\n\n".join(sections)
