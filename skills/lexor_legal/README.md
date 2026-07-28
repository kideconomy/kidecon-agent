# lexor-legal

Read-only informational access to the Lexor legal engineering platform.

This skill wires the agent directly to Lexor over HTTP using a per-agent JWT
stored in the OS keyring. It is **informational only**: the agent can answer
questions about entity formation, legal terms, taxonomy, compliance, and
registered entities, but cannot draft, register, trigger, or modify anything
in the Lexor corpus.

## Staff-only

Three independent layers enforce staff-only access:

1. **Provisioning** — only staff agents have `api_key_lexor` in the keyring.
   A non-staff agent has no credential and the call fails at the keyring.
2. **Capability cap** — the JWT carries the `legal` role, which the Lexor
   server enforces as read-only. Even if a token is stolen, it cannot draft
   or register.
3. **Local tier gate** — `LexorClient` refuses unless `agent_hub_tier >= 3`,
   with a transparent block message otherwise.

## Setup

1. Ask the Lexor admin to issue a `legal`-role token:
   ```bash
   lexor mcp issue-token --user <agent-name> --role legal --label "kidecon agent"
   ```
2. Store it in the keyring:
   ```bash
   kidecon key add --name lexor --value <jwt>
   ```
3. Enable in `~/.config/kidecon/kidecon.yaml`:
   ```yaml
   lexor:
     enabled: true
     base_url: "http://localhost:8000"
     role: "legal"
     timeout: 15
   ```
4. Verify: `kidecon doctor` — `lexor` appears under Keys (optional, present
   when provisioned).

## Allowed tools (read-only allowlist)

`blueprint.list`, `blueprint.get`, `term.normalize`, `search.semantic`,
`compliance.report`, `entity.list`, `entity.get`, `peer.list`, `pattern.get`,
`epic.status`, `taxonomy.search`, `context.build`

`blueprint.plan` and all Tier 3/4 tools (draft/register/trigger) are
deliberately excluded — they create artifacts and are non-informational.

## How the agent invokes Lexor

The cognitive engine adds a `lexor_call` step action to its PLAN schema. When
a user asks a legal question, the planner emits a `lexor_call` step with a
tool name from the allowlist and parameters. The engine dispatches it to
`LexorClient.call`, scrubs the result for PII deterministically, and feeds it
back into the turn as step output. Lexor results are never passed through
unfiltered.
