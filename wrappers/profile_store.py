"""Agent profile store — manages multiple agent profiles on disk.

Replaces the single-keyring model with a directory of JSON profiles:
    ~/.config/kidecon/agents/<name>.json

Each profile file holds non-secret metadata {agent_id, name, ke_username, role}.
The JWT is a credential and is stored in the OS keyring under a per-agent key
(jwt_<name>), never on disk. The active profile is tracked via
~/.config/kidecon/agents/.active
"""

import contextlib
import json
import logging
import pathlib
import secrets
import uuid
from typing import Optional

import httpx

from wrappers.keys import KEYRING_SERVICE
from wrappers.keys import jwt_key

logger = logging.getLogger(__name__)

PROFILES_DIR = pathlib.Path.home() / ".config" / "kidecon" / "agents"

VALID_ROLES = {"orchestrator", "worker", "standalone"}

# Re-export the shared helper under the local name used throughout this module.
from wrappers._http import hub_detail as _response_detail  # noqa: E402


class Profile:
    """An agent profile stored on disk."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        jwt: str | None = None,
        ke_username: str | None = None,
        role: str = "standalone",
    ):
        self.agent_id = agent_id
        self.name = name
        self.jwt = jwt
        self.ke_username = ke_username
        self.role = role if role in VALID_ROLES else "standalone"

    def to_dict(self) -> dict:
        # jwt is intentionally omitted — it lives in the keyring, never on disk.
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "ke_username": self.ke_username,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            agent_id=d["agent_id"],
            name=d["name"],
            jwt=d.get("jwt"),  # legacy fallback: old files may still embed a jwt
            ke_username=d.get("ke_username"),
            role=d.get("role", "standalone"),
        )

    @property
    def path(self) -> pathlib.Path:
        return PROFILES_DIR / f"{self.name}.json"

    @property
    def pid_path(self) -> pathlib.Path:
        return PROFILES_DIR / f"{self.name}.pid"

    @property
    def log_path(self) -> pathlib.Path:
        return pathlib.Path.home() / "kidecon" / "logs" / f"{self.name}.log"


def _ensure_dirs() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    (pathlib.Path.home() / "kidecon" / "logs").mkdir(parents=True, exist_ok=True)


def save_profile(profile: Profile) -> None:
    """Persist a profile: non-secret fields to disk, the JWT to the keyring."""
    _ensure_dirs()
    if profile.jwt:
        import keyring

        keyring.set_password(KEYRING_SERVICE, jwt_key(profile.name), profile.jwt)
    profile.path.write_text(json.dumps(profile.to_dict(), indent=2))
    profile.path.chmod(0o600)


def load_profile(name: str) -> Profile | None:
    """Load a profile by name. The JWT is resolved from the keyring, not disk."""
    path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        profile = Profile.from_dict(data)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Corrupt profile %s: %s", name, e)
        return None

    import keyring

    try:
        keyring_jwt = keyring.get_password(KEYRING_SERVICE, jwt_key(name))
    except Exception:
        keyring_jwt = None
    if keyring_jwt:
        profile.jwt = keyring_jwt
    return profile


def delete_profile(name: str) -> bool:
    """Delete a profile (file + pid + its keyring JWT). Returns True on success."""
    path = PROFILES_DIR / f"{name}.json"
    pid_path = PROFILES_DIR / f"{name}.pid"
    if path.exists():
        path.unlink()
    if pid_path.exists():
        pid_path.unlink()
    import keyring

    with contextlib.suppress(Exception):
        keyring.delete_password(KEYRING_SERVICE, jwt_key(name))
    return True


def list_profiles() -> list[str]:
    """List all profile names from disk."""
    _ensure_dirs()
    names = []
    for p in PROFILES_DIR.glob("*.json"):
        names.append(p.stem)
    return sorted(names)


def list_profile_objects() -> list[Profile]:
    """List all loaded profiles."""
    profiles = []
    for name in list_profiles():
        profile = load_profile(name)
        if profile:
            profiles.append(profile)
    return profiles


def resolve_profile(name: str | None = None) -> Profile | None:
    """Resolve a profile by explicit name only.

    Agent identity is always explicit: there is no active-profile,
    single-profile, or legacy-keyring fallback. Calling with no name returns
    None so callers must fail loudly rather than guess.
    """
    if name:
        return load_profile(name)
    return None


def create_profile(
    name: str,
    role: str = "standalone",
    hub_url: str | None = None,
    ke_token: str | None = None,
    kideconomy_api_url: str | None = None,
) -> Profile:
    """Create and register a new agent profile.

    Generates a new agent_id and registers with the hub if hub_url + ke_token provided.
    """
    _ensure_dirs()

    existing = load_profile(name)
    if existing:
        raise FileExistsError(f"Profile '{name}' already exists.")

    agent_id = str(uuid.uuid4())
    profile = Profile(agent_id=agent_id, name=name, role=role)

    if hub_url and ke_token:
        payload: dict = {"agent_id": agent_id, "name": name, "platform": "cli"}
        payload["ke_token"] = ke_token
        response = httpx.post(
            f"{hub_url.rstrip('/')}/api/register_agent",
            json=payload,
            timeout=15,
        )
        if response.status_code == 409:
            detail = _response_detail(response, "Name already taken")
            raise RuntimeError(f"Agent name '{name}' already registered. Use a different name or delete the existing profile.")
        if response.status_code == 403:
            detail = _response_detail(
                response,
                "Agent has been deactivated or is linked to a different KidEconomy account.",
            )
            raise RuntimeError(f"Registration rejected: {detail}")
        if response.status_code == 401:
            raise RuntimeError("KidEconomy token rejected by the hub. Run 'kidecon agents create' again with the correct credentials.")
        response.raise_for_status()
        data = response.json()
        profile.jwt = data["jwt"]

    save_profile(profile)
    return profile


def rotate_jwt(profile: Profile, hub_url: str, ke_token: str) -> str:
    """Re-register an existing agent to get a fresh JWT."""
    payload: dict = {"agent_id": profile.agent_id, "name": profile.name, "platform": "cli"}
    payload["ke_token"] = ke_token
    response = httpx.post(
        f"{hub_url.rstrip('/')}/api/register_agent",
        json=payload,
        timeout=15,
    )
    if response.status_code == 403:
        detail = _response_detail(
            response,
            "Agent has been deactivated or is linked to a different KidEconomy account.",
        )
        raise RuntimeError(f"Re-registration rejected: {detail}")
    if response.status_code == 401:
        raise RuntimeError("KidEconomy token rejected by the hub.")
    if response.status_code == 409:
        detail = _response_detail(response, "Agent name already taken.")
        raise RuntimeError(f"Re-registration failed: {detail}")
    response.raise_for_status()
    data = response.json()
    profile.jwt = data["jwt"]
    save_profile(profile)
    return profile.jwt


def write_pid(profile: Profile, pid: int) -> None:
    """Write PID file for a running agent."""
    _ensure_dirs()
    profile.pid_path.write_text(str(pid))


def read_pid(profile: Profile) -> int | None:
    """Read PID file for an agent. Returns None if not running."""
    if not profile.pid_path.exists():
        return None
    try:
        pid = int(profile.pid_path.read_text().strip())
        os_kill = __import__("os").kill
        os_kill(pid, 0)
        return pid
    except (ValueError, OSError):
        return None


def clear_pid(profile: Profile) -> None:
    """Remove PID file."""
    if profile.pid_path.exists():
        profile.pid_path.unlink()


def get_log_path(name: str) -> pathlib.Path:
    return pathlib.Path.home() / "kidecon" / "logs" / f"{name}.log"


def set_profile_role(name: str, new_role: str) -> Profile | None:
    """Change the role of an existing profile. Returns updated profile or None."""
    profile = load_profile(name)
    if not profile:
        return None
    if new_role not in VALID_ROLES:
        return None
    profile.role = new_role
    save_profile(profile)
    return profile


def nuke_all_profiles() -> list[str]:
    """Delete all agent profiles, their keyring JWTs, and the agents directory."""
    import shutil

    import keyring

    names = list_profiles()
    for name in names:
        with contextlib.suppress(Exception):
            keyring.delete_password(KEYRING_SERVICE, jwt_key(name))
    if PROFILES_DIR.exists():
        shutil.rmtree(PROFILES_DIR)
    return names
