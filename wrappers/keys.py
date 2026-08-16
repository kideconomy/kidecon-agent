"""Keyring manager — the single source of truth for credential keys.

All credentials live only in the OS keyring, never on disk (AGENTS.md §3).
Key names are centralized here; modules must import from this module rather
than defining their own key strings or formatting names inline.

Key namespaces (by prefix, so keys never collide and are enumerable):
  - ``hub_jwt`` / ``agent_id``        legacy single-agent (read-only fallback)
  - ``kideconomy_*``                  KidEconomy account credentials
  - ``jwt_<agent>``                   per-agent JWT (never persisted to disk)
  - ``api_key_<provider>``            third-party API keys
"""

import contextlib
import json
import logging
import pathlib

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "kidecon-agent"

# Enumeration manifest. Keyring backends do not reliably enumerate, so we keep
# a JSON list of registered API-key providers (names only, never values).
INDEX_PATH = pathlib.Path.home() / ".config" / "kidecon" / "keys.json"

# Canonical key names. Use these constants, never string literals.
KEY_JWT = "hub_jwt"          # legacy single-agent JWT (fallback during migration)
KEY_AGENT_ID = "agent_id"    # legacy single-agent agent ID
KEY_KE_USERNAME = "kideconomy_username"
KEY_KE_TOKEN = "kideconomy_token"


def jwt_key(agent_name: str) -> str:
    """Per-agent JWT key. Never persisted to disk."""
    return f"jwt_{agent_name}"


def api_key(provider: str) -> str:
    """Third-party API key, keyed by provider name."""
    return f"api_key_{provider}"


def get(key: str) -> str | None:
    """Read a value from the keyring. Returns None if absent or unavailable."""
    import keyring

    with contextlib.suppress(Exception):
        return keyring.get_password(KEYRING_SERVICE, key)
    return None


def set_(key: str, value: str) -> None:
    """Write a value to the keyring."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, key, value)


def delete(key: str) -> None:
    """Remove a value from the keyring (best-effort)."""
    import keyring

    with contextlib.suppress(Exception):
        keyring.delete_password(KEYRING_SERVICE, key)


def list_api_keys() -> list[str]:
    """Enumerate registered API-key provider names from the manifest."""
    if INDEX_PATH.exists():
        with contextlib.suppress(Exception):
            return json.loads(INDEX_PATH.read_text())
    return []


def save_api_keys(providers: list[str]) -> None:
    """Persist the API-key provider manifest (sorted, deduplicated)."""
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(sorted(set(providers)), indent=2))
