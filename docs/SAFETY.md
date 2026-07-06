# Kidecon Agent -- Safety Measures

This document explains the safety controls in place for your Kidecon Agent installation.
You can ask your agent "what safety measures are in place?" at any time for a current summary.

## Access control

All users have the same experience and access level through the agent. The agent does not
distinguish between adult and child users. Staff-level access is controlled server-side by
the hub, not by the agent.

## Secret storage

- All secrets (JWT tokens, API keys, agent ID) are stored in your operating system's
  keyring. Secrets are never written to disk or included in configuration files.
- The `kidecon key list` command shows masked keys only -- full values are never printed.

## Script sandbox

User scripts placed in `~/kidecon/user_scripts/` run under these restrictions:

- **Path containment** -- scripts can only access `~/kidecon/workspace/`. Attempts to read
  or write outside this directory are blocked.
- **60-second timeout** -- long-running scripts are terminated. If your script needs more
  time, split the work into smaller steps.
- **First-run approval** -- every new script requires explicit approval before its first
  execution. The approval prompt describes what the script will do (internet access, file
  operations, etc.).
- **Audit trail** -- every script approval is timestamped and logged to
  `~/kidecon/.approved_scripts` so you can audit what has been approved and when.

## Tool gate

The `kidecon.yaml` configuration file defines which tools your agent is allowed to invoke:

- **allow** -- tools always permitted (file_read, file_append_markdown, hub_call,
  user_script_execute, message_user).
- **deny** -- tools always blocked (file_write_binary, shell_execute, file_delete).
- **require_approval** -- tools that need your confirmation before first use
  (user_script_first_run, hub_collaboration_request).

## Code execution

The agent never executes generated code without your explicit approval. There is no path
for `exec`, `eval`, or automated code generation in the runtime.

## When something is blocked

Every block produces a clear message with three parts:

1. **What happened** -- which action was blocked.
2. **Why** -- the specific reason.
3. **What to do next** -- how to resolve the issue.

Examples:
- "Script 'analyze.py' requires first-run approval. This script will access the internet
  and write to ~/kidecon/workspace/. Approve? [y/n]"
- "Script 'cleanup.py' timed out after 60s. To increase the timeout, edit the script or
  split long-running work into smaller steps."

## Checking your posture

- Run `kidecon doctor` for a full diagnostic of your agent's health and safety posture.
- Run `kidecon status` to see your agent ID, registration status, and tier.
- Ask your agent "what safety measures are in place?" -- it will respond with sandbox
  status, approved scripts count, path containment boundary, keyring status, and whether
  the hub connection uses JWT.