# AGENTS.md — KidEconomy Agent Working Constitution

Read at the start of every session. Canonical source of truth for stack, conventions, and safety rules.

## 1. Stack
- **Core:** Python 3.14, Click CLI, httpx, keyring, PyYAML.
- **No server, no database.** This is a client-side wrapper + installer.
- **Secrets:** OS keyring only. Never write secrets to disk.
- **Config:** `kidecon.yaml` (YAML). Read by wrappers and CLI.

## 2. Architectural Conventions
- **Wrappers** (`wrappers/`): thin Python classes/functions that call the hub or execute local tools.
- **CLI** (`cli/`): Click commands that orchestrate wrappers. No business logic in CLI.
- **Sandbox** (`wrappers/sandbox.py`): isolated subprocess execution of user scripts.
- **Logging:** Every .py file starts with `import logging; logger = logging.getLogger(__name__)`.

### 2.1 Agent identity is always explicit
- **No active profile, no single-profile auto-pick, no legacy-keyring fallback.** `resolve_profile(name)` resolves a profile by explicit name only and returns `None` when none is given. Guessing produced phantom agents (e.g. a stale profile auto-selected after another was deleted), so it is banned.
- Hub-talking commands (`skills submit|mine|discover|inspect`, `admin ...`) require the global `--agent <name>` option. `start`/`status`/`stop` require `--name`.
- **Auth is per-agent; authority is per-user.** Every agent has its own JWT (`sub = agent_id`, signed with its per-agent `jwt_secret`). The JWT carries no tier/role: the hub resolves `agent -> user` and reads `tier`/`is_staff` live, so promotion/demotion affects all of a user's agents instantly.
- **Skills are owned by the `User`, not the agent.** `Skill.user_id` points at the user; `Skill.originated_from_agent_id` is provenance only. Deleting or rotating an agent never orphans a skill.
- **Skills declare their tools (`definition.tools`) and the runtime enforces them.** The cognition loop refuses any tool a skill does not declare (`docs_sync`, `message_user`, `file_read`, `text_diff`, `file_append_markdown`, `lexor:<tool>`, `hub:<tool>`). A skill with no `tools` key is ungated (legacy); an empty `tools: []` blocks every tool.

## 3. Safety & Git Rules
- **NO COMMITS.** Never `git commit` or `git add` unless explicitly requested.
- **Never hardcode secrets, and never write secrets to disk.** All credentials (JWTs, API keys, KE tokens) live exclusively in the OS keyring via `keyring.set_password`. They must never be written to any file — no JSON profiles, YAML config, logs, caches, or any `write_text()`/`json.dump()`/`open()` path. Any object that holds a secret and is serialized (e.g. a `to_dict()`) MUST exclude the secret from its output. Only non-secret identifiers (`agent_id`, usernames) may be persisted to files.
- Sandbox must enforce: no filesystem access outside designated dirs, 60s timeout, first-run approval.

## 4. Access Control & Safety

### 4.1 Posture
- The agent operates on behalf of a user. All non-staff users have identical access and experience through the agent. The agent does not distinguish between adult and child users -- content filtering, tool gating, and sandbox restrictions apply uniformly to all non-staff users.
- Staff users (tier 3 on the hub) are the only exception with elevated access. Elevation is controlled server-side by the hub, not by the agent.

### 4.2 Sandbox transparency
- When `UserScriptSandbox` blocks execution (first-run approval, timeout, permission denied), the user MUST be clearly informed: (1) what was blocked, (2) why, (3) what to do next.
- Example: "Script 'analyze.py' requires first-run approval. This script will access the internet and write to ~/kidecon/workspace/. Approve? [y/n]"
- Example: "Script 'cleanup.py' timed out after 60s. To increase the timeout, edit the script or split long-running work into smaller steps."

### 4.3 Audit trail
- Every script approval writes a timestamped, append-only entry to `~/kidecon/.approved_scripts` with: timestamp, script name, action (approved/denied), and reason (user-provided or auto).

### 4.4 No silent code execution
- The agent runtime must never execute generated code without explicit user approval. A test must assert that `exec`, `eval`, and `subprocess`-of-generated-content paths are blocked or approval-gated.

### 4.5 User questions
- Users must be able to ask "what safety measures are in place?" The agent must respond with: sandbox status, approved scripts count, path containment boundary, keyring status, and whether the hub connection uses JWT.

## 5. Testing Discipline
- pytest with simple unit tests for wrappers and CLI.
- Mock httpx responses for hub_client tests.
- Test sandbox permission enforcement.

## 6. Review
- After non-trivial changes, run `/review` — invokes `reviewer-safety`.
