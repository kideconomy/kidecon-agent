"""Keyring manager — the single source of truth for credential keys.

All credentials live only in the OS keyring, never on disk (AGENTS.md §3).
Key names are centralized here; modules must import from this module rather
than defining their own key strings or formatting names inline.

Key namespaces (by prefix, so keys never collide and are enumerable):
  - ``hub_jwt`` / ``agent_id``        legacy single-agent (read-only fallback)
  - ``kideconomy_*``                  KidEconomy account credentials
  - ``user_jwt``                      account-level USER JWT (no agent needed)
  - ``jwt_<agent>``                   per-agent JWT (never persisted to disk)
  - ``api_key_<provider>``            third-party API keys
"""

import contextlib
import json
import logging
import pathlib
from dataclasses import dataclass

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
KEY_USER_JWT = "user_jwt"    # account-level USER JWT (minted from a verified KE token)


@dataclass(frozen=True)
class KeySpec:
    """Static description of a known credential slot.

    `keyring_key` resolves the real keyring key name for a catalog entry:
    provider entries are stored under ``api_key_<name>``; legacy/account
    entries already carry their keyring key as `key`.
    """

    key: str
    label: str
    description: str
    secret: bool = True
    category: str = "provider"          # provider | agent | legacy | account
    required: bool = False
    optional: bool = False

    @property
    def keyring_key(self) -> str:
        return api_key(self.key) if self.category == "provider" else self.key

    def fetch(self) -> str | None:
        return get(self.keyring_key)


_MASK_CHARS = 8


def mask_secret(value: str | None) -> str:
    """Mask a secret for display: first4...last4, or `***` / `(not set)`."""
    if not value:
        return "(not set)"
    if len(value) > _MASK_CHARS:
        return f"{value[:4]}...{value[-4:]}"
    return "***"


@dataclass(frozen=True)
class KeyEntry:
    """One enumerated row: a resolved key plus its metadata.

    `value` holds the live credential only in memory — never logged or
    serialized. Consumers should render `masked` (which respects `secret`)
    unless they have a specific need for the raw value.
    """

    key: str
    label: str
    value: str | None
    description: str
    secret: bool = True
    category: str = "provider"
    required: bool = False
    optional: bool = False

    @property
    def masked(self) -> str:
        if not self.secret:
            return self.value or "(not set)"
        return mask_secret(self.value)


# Well-known third-party providers. Shown in `key list` even when unset so the
# user knows what a credential is for and whether it is expected on this box.
WELL_KNOWN_PROVIDERS: list[KeySpec] = [
    KeySpec("openrouter", "openrouter", "LLM inference via OpenRouter", required=True),
    KeySpec("lexor", "lexor", "Lexor legal MCP (staff-only, read-only)", optional=True),
]

# Legacy single-agent slots. They are a read-only fallback during migration and
# are legitimately unset once explicit agent profiles exist.
LEGACY_KEY_SPECS: list[KeySpec] = [
    KeySpec(
        KEY_JWT,
        "hub_jwt",
        "Legacy single-agent JWT (per-agent JWTs live under jwt_<agent>)",
        category="legacy",
    ),
    KeySpec(
        KEY_AGENT_ID,
        "agent_id",
        "Legacy single-agent agent ID (per-agent IDs live in the profile)",
        secret=False,
        category="legacy",
    ),
]

# KidEconomy account credentials (shared, not per-agent).
ACCOUNT_KEY_SPECS: list[KeySpec] = [
    KeySpec(
        KEY_KE_USERNAME,
        KEY_KE_USERNAME,
        "KidEconomy account username",
        secret=False,
        required=True,
        category="account",
    ),
    KeySpec(
        KEY_KE_TOKEN,
        KEY_KE_TOKEN,
        "KidEconomy account token",
        required=True,
        category="account",
    ),
    KeySpec(
        KEY_USER_JWT,
        KEY_USER_JWT,
        "Account USER JWT — lets `status --me`/`--refresh` run without --agent",
        optional=True,
        category="account",
    ),
]


def _agent_entries(profile: object | None) -> list[KeyEntry]:
    """Per-agent keys: JWT (keyring under jwt_<name>) + non-secret profile fields."""
    if profile is None:
        return []
    name = getattr(profile, "name", "")
    if not name:
        return []
    jwt = getattr(profile, "jwt", None)
    if jwt is None:
        jwt = get(jwt_key(name))
    return [
        KeyEntry(
            jwt_key(name),
            f"jwt_{name}",
            jwt,
            f"JWT for agent '{name}'",
            secret=True,
            category="agent",
            required=True,
        ),
        KeyEntry(
            f"{name}.agent_id",
            f"agent_id: {name}",
            getattr(profile, "agent_id", None),
            f"Hub agent ID for '{name}'",
            secret=False,
            category="agent",
            required=True,
        ),
        KeyEntry(
            f"{name}.ke_username",
            f"ke_username: {name}",
            getattr(profile, "ke_username", None),
            f"KidEconomy account for '{name}'",
            secret=False,
            category="agent",
        ),
    ]


def enumerate_keys(profile: object | None = None) -> list[KeyEntry]:
    """Enumerate every credential the agent knows about.

    Data-driven: legacy slots, per-agent keys, and provider keys are merged
    from their catalogs (plus anything in the user's provider manifest), so
    the CLI never hardcodes a row for a key.
    """
    entries: list[KeyEntry] = [
        KeyEntry(
            spec.keyring_key,
            spec.label,
            spec.fetch(),
            spec.description,
            secret=spec.secret,
            category=spec.category,
            required=spec.required,
            optional=spec.optional,
        )
        for spec in [*LEGACY_KEY_SPECS, *ACCOUNT_KEY_SPECS]
    ]

    if profile is not None:
        entries.extend(_agent_entries(profile))
    else:
        from wrappers.profile_store import list_profile_objects

        with contextlib.suppress(Exception):
            for prof in list_profile_objects():
                entries.extend(_agent_entries(prof))

    entries.extend(
        KeyEntry(
            spec.keyring_key,
            spec.label,
            spec.fetch(),
            spec.description,
            secret=True,
            category="provider",
            required=spec.required,
            optional=spec.optional,
        )
        for spec in well_known_provider_specs()
    )

    return entries


def well_known_provider_specs() -> list[KeySpec]:
    """Provider specs: well-known services merged with the user manifest.
    Returns the catalog in display order (required first, then name)."""
    specs = {s.key: s for s in WELL_KNOWN_PROVIDERS}
    for provider in list_api_keys():
        specs.setdefault(provider, KeySpec(provider, provider, "Provider-added key", optional=True))
    return sorted(specs.values(), key=lambda s: (not s.required, s.key))


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
