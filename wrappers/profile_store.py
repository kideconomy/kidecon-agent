"""Agent profile store — manages multiple agent profiles on disk.

Replaces the single-keyring model with a directory of JSON profiles:
    ~/.config/kidecon/agents/<name>.json

Each profile contains {agent_id, name, jwt, ke_username, role}.
The active profile is tracked via ~/.config/kidecon/agents/.active
"""

import json
import logging
import pathlib
import secrets
import uuid
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PROFILES_DIR = pathlib.Path.home() / ".config" / "kidecon" / "agents"
ACTIVE_FILE = PROFILES_DIR / ".active"
KEYRING_SERVICE = "kidecon-agent"
KEY_JWT = "hub_jwt"
KEY_AGENT_ID = "agent_id"
KEY_KE_USERNAME = "kideconomy_username"

VALID_ROLES = {"orchestrator", "worker", "standalone"}


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
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "jwt": self.jwt,
            "ke_username": self.ke_username,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            agent_id=d["agent_id"],
            name=d["name"],
            jwt=d.get("jwt"),
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
    """Persist a profile to disk."""
    _ensure_dirs()
    profile.path.write_text(json.dumps(profile.to_dict(), indent=2))
    profile.path.chmod(0o600)


def load_profile(name: str) -> Profile | None:
    """Load a profile by name from disk. Returns None if not found."""
    path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Profile.from_dict(data)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Corrupt profile %s: %s", name, e)
        return None


def delete_profile(name: str) -> bool:
    """Delete a profile. Returns True if the file was removed."""
    path = PROFILES_DIR / f"{name}.json"
    pid_path = PROFILES_DIR / f"{name}.pid"
    if path.exists():
        path.unlink()
    if pid_path.exists():
        pid_path.unlink()
    if get_active() == name:
        _clear_active()
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


def set_active(name: str) -> None:
    """Set the active profile name."""
    _ensure_dirs()
    ACTIVE_FILE.write_text(name)


def get_active() -> str | None:
    """Get the active profile name."""
    if not ACTIVE_FILE.exists():
        return None
    return ACTIVE_FILE.read_text().strip() or None


def _clear_active() -> None:
    if ACTIVE_FILE.exists():
        ACTIVE_FILE.unlink()


def resolve_profile(name: str | None = None) -> Profile | None:
    """Resolve a profile to use. Precedence: explicit name > active > single-profile auto-pick > legacy keyring > None."""
    if name:
        return load_profile(name)

    active = get_active()
    if active:
        return load_profile(active)

    profiles = list_profiles()
    if len(profiles) == 1:
        return load_profile(profiles[0])

    return _load_from_keyring()


def _load_from_keyring() -> Profile | None:
    """Legacy fallback: load the single agent from keyring."""
    try:
        import keyring

        agent_id = keyring.get_password(KEYRING_SERVICE, KEY_AGENT_ID)
        jwt = keyring.get_password(KEYRING_SERVICE, KEY_JWT)
        ke_username = keyring.get_password(KEYRING_SERVICE, KEY_KE_USERNAME)
        if agent_id:
            return Profile(
                agent_id=agent_id,
                name="keyring-legacy",
                jwt=jwt,
                ke_username=ke_username,
                role="standalone",
            )
    except Exception:
        pass
    return None


def _migrate_keyring_to_profile(name: str) -> Profile | None:
    """One-time migration: move keyring credentials into a named profile.
    
    Does NOT delete keyring entries — that's the user's choice.
    """
    legacy = _load_from_keyring()
    if not legacy:
        return None
    legacy.name = name
    save_profile(legacy)
    set_active(name)
    logger.info("Migrated keyring agent to profile '%s'", name)
    return legacy


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
            detail = response.json().get("detail", "Name already taken")
            raise RuntimeError(f"Agent name '{name}' already registered. Use a different name or delete the existing profile.")
        if response.status_code == 403:
            detail = response.json().get("detail", "Agent has been deactivated")
            raise RuntimeError(f"Registration rejected: {detail}")
        if response.status_code == 401:
            raise RuntimeError("KidEconomy token rejected by the hub. Run 'kidecon agents create' again with the correct credentials.")
        response.raise_for_status()
        data = response.json()
        profile.jwt = data["jwt"]

    save_profile(profile)
    if not get_active():
        set_active(name)
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
    """Delete all agent profiles and the agents directory. Returns list of deleted names."""
    import shutil
    names = list_profiles()
    if PROFILES_DIR.exists():
        shutil.rmtree(PROFILES_DIR)
    return names
