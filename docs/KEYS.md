# Key Management

This documents how credentials are named, stored, and accessed in the agent.
The single source of truth is `wrappers/keys.py` — do **not** define key names
elsewhere or use string literals for keyring keys.

## Security posture (see `AGENTS.md` §3)

- **Credentials never touch disk.** JWTs, API keys, and tokens live only in the
  OS keyring. They are never written to JSON profiles, YAML config, logs,
  caches, or any `write_text()` / `json.dump()` path.
- **Serialization must not leak secrets.** Any object that holds a credential
  and defines `to_dict()` / `save()` / `__str__()` must EXCLUDE the credential
  from its output. (Example: `Profile.to_dict()` omits `jwt`.)
- **Non-secret identifiers** (`agent_id`, usernames) may live in files.

## Key namespaces

All keys are under keyring service `kidecon-agent`:

| Pattern | Purpose | Persisted to disk? |
|---|---|---|
| `hub_jwt` / `agent_id` | legacy single-agent (read-only fallback) | no |
| `kideconomy_username` / `kideconomy_token` | KidEconomy account credentials | no |
| `jwt_<agent>` | per-agent JWT | **never** |
| `api_key_<provider>` | third-party API keys | no |

## Using `wrappers/keys.py`

```python
from wrappers.keys import KEYRING_SERVICE, KEY_KE_TOKEN, jwt_key, api_key, get, set_, delete

key = jwt_key("legal-bot")          # "jwt_legal-bot"
key = api_key("openrouter")         # "api_key_openrouter"

token = get(KEY_KE_TOKEN)           # read (None if absent)
set_(api_key("github-docs"), pat)   # write
delete(jwt_key("legal-bot"))        # remove
```

## Enumeration

Keyring backends do not reliably enumerate, so API-key *provider names* (not
values) are tracked in a manifest at `~/.config/kidecon/keys.json`, managed via
`list_api_keys()` / `save_api_keys()` in `wrappers/keys.py`.

`kidecon key list` (and `kidecon doctor`) are **catalog-driven**: they render
whatever a key catalog in `wrappers/keys.py` enumerates, so adding a key is a
one-line registration, never CLI hardcoding. The catalog groups keys into:

- **Legacy slots** (`LEGACY_KEY_SPECS`) — `hub_jwt`, `agent_id`. Read-only
  fallback during migration; legitimately unset once explicit agent profiles
  exist, so they render as `(not set)` instead of a confusing error.
- **Account credentials** (`ACCOUNT_KEY_SPECS`) — `kideconomy_username`,
  `kideconomy_token`.
- **Per-agent keys** — JWT stored under `jwt_<agent>` (from the keyring, never
  disk) plus `agent_id` / `ke_username` from the profile file. Shown for the
  resolved `--agent`, or for every profile when no `--agent` is given.
- **Provider keys** (`WELL_KNOWN_PROVIDERS` + the user manifest) — e.g.
  `openrouter` (required) and `lexor` (optional).

`enumerate_keys(profile=None)` returns the merged, resolved list of `KeyEntry`
rows (see `wrappers/keys.py`). Consumers render these rows fluidly and never
hardcode a key name.
