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
`list_api_keys()` / `save_api_keys()` in `wrappers/keys.py`. This lets
`kidecon key list` enumerate keys without parsing name prefixes.
