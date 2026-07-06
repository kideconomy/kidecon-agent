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

## 3. Safety & Git Rules
- **NO COMMITS.** Never `git commit` or `git add` unless explicitly requested.
- Never hardcode secrets. Use keyring.
- Never write API keys, JWTs, or credentials to files.
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
