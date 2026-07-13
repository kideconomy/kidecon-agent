# Architecture

KidEconomy Agent is the user-facing, public repo: a thin CLI wrapper + Python library + install script. It is a **client sidecar** — no server, no database. It installs Hermes (from Nous Research), places the KidEconomy config, registers the agent with the hub, and provides approved local tools plus a sandboxed user-script executor.

## Client Topology

```mermaid
flowchart TD
    subgraph agent["kidecon-agent (this repo)"]
        user([user])
        cli["kidecon CLI<br/>cli/kidecon.py"]
        hubclient["wrappers/hub_client.py"]
        tools["wrappers/tools.py"]
        sandbox["wrappers/sandbox.py<br/>(UserScriptSandbox)"]
        userscripts["~/kidecon/user_scripts/*.py"]
    end
    keyring[("keyring<br/>JWT, agent_id, API keys")]
    hub["kidecon-hub<br/>(separate repo, HTTP API)"]

    user --> cli
    cli --> hubclient
    cli --> tools
    cli --> sandbox
    hubclient <-->|read / write| keyring
    sandbox -->|subprocess, 60s timeout| userscripts
    hubclient -->|HTTP| hub

    hub -. "POST" .-> reg["/api/register_agent"]
    hub -. "POST" .-> mcp["/api/mcp/call"]
    hub -. "GET" .-> poll["/api/messages/poll"]
    hub -. "POST" .-> resp["/api/messages/{id}/respond"]
    hub -. "POST" .-> send["/api/messages/send"]
    hub -. "GET" .-> disc["/api/skills/discover"]
    hub -. "GET" .-> agent_ep["/api/agent/{agent_id}"]
```

## Component Responsibilities

| Path                       | Role                                                                                |
|----------------------------|-------------------------------------------------------------------------------------|
| `kidecon.yaml`             | Default config: provider, hub_url, tool_gate (allow/deny/require_approval), update_channel, hermes_version. |
| `wrappers/__init__.py`     | Package marker; logger.                                                            |
| `wrappers/hub_client.py`   | `HubClient` — registers agent, stores JWT in keyring, calls hub MCP tools, polls/responds to messages, discovers skills, reads tier. |
| `wrappers/tools.py`        | Approved local tools: `file_read`, `file_append_markdown`, `message_user`. Workspace-scoped via `ALLOWED_BASE_DIR`. |
| `wrappers/sandbox.py`      | `UserScriptSandbox` — runs user scripts under `~/kidecon/user_scripts/` with 60s timeout + first-run approval gate. |
| `wrappers/runtime.py`      | Hermes runtime loop — long-polls hub, routes messages through safety firewall and LLM tiers, responds via broker. |
| `wrappers/safety_firewall.py` | `SafetyFirewall` — synchronous ingress/egress safety interceptor for Discord traffic using a paid Llama-3-8B model. Fail-closed. |
| `shared/llm_clients/`      | **Vendored copy** from kidecon-hub. Multi-provider LLM abstraction (OpenRouter, Together, DeepSeek). **DO NOT EDIT HERE.** Canonical source is in `kidecon-hub/shared/llm_clients/`. Run `make sync-llm` to pull changes. |
| `cli/__init__.py`          | Package marker; logger.                                                            |
| `cli/kidecon.py`           | Click CLI: `setup`, `start`, `stop`, `status`, `update`, `key` (add/list), `tier`, `skills` (list/browse). Thin orchestration only. |
| `install.sh`               | Bootstrap: venv, deps, place config, prompt OpenRouter key → keyring, install Hermes (stubbed), register agent → JWT → keyring. |
| `requirements.txt`         | Runtime + dev deps.                                                                |
| `pyproject.toml`           | ruff (kidecon rules minus `DJ`, target py311) + pytest config.                     |
| `skills/`                  | Community-contributed starter skills (see `skills/README.md`).                    |

## Data Flow

1. **Install** (`install.sh`): creates `env/`, installs deps, copies `kidecon.yaml` to `~/.config/kidecon/`, prompts for OpenRouter key -> keyring, runs `kidecon setup`.
2. **Register** (`kidecon setup`): `HubClient.register()` POSTs to `/api/register_agent`, stores JWT + agent_id in keyring.
3. **Run** (`kidecon start`): enters the Hermes runtime loop — pulls MCP manifest from hub, long-polls for messages, routes each message through ingress safety → LLM (with dynamic tier selection) → egress safety → respond. Handles SIGINT/SIGTERM (mark offline), 401 (prompt re-register), and network dropouts (exponential backoff).
4. **Tool call**: agent invokes an allowed tool — local (`wrappers/tools.py`) or hub (`HubClient.hub_call()` via `/api/mcp/call`).
5. **User script**: `UserScriptSandbox.execute()` runs a script from `~/kidecon/user_scripts/`; first run requires approval (recorded in `~/kidecon/.approved_scripts`); 60s timeout enforced.
6. **Messages**: `HubClient.poll_messages()` → `/api/messages/poll`; respond via `/api/messages/{id}/respond`; send via `/api/messages/send`.

## Secrets

All secrets live in the OS keyring under service `kidecon-agent`:
- `agent_id` — generated UUID, created on first use.
- `hub_jwt` — issued by hub on `register`.
- `api_key_<name>` — user-added API keys (e.g. `api_key_openrouter`).

No secret is ever written to disk or logged. `kidecon key list` masks all values.

## Multi-Agent Profile Store

The CLI now supports multiple agent profiles on the same machine, replacing the single-keyring model:

```
~/.config/kidecon/
  kidecon.yaml                    # shared config (hub URL, KE API URL, LLM models)
  agents/
    johnnys-laptop.json           # {agent_id, name, jwt, ke_username, role}
    coding-bot.json               # {agent_id, name, jwt, ke_username, role}
    .active                       # name of the currently active profile
```

**Profile commands:** `kidecon agents list`, `kidecon agents create --name <n> --role orchestrator|worker|standalone`, `kidecon agents delete --name <n>`.

Profiles are created with `chmod 0600` to protect the JWT. Legacy keyring agents are auto-migrated on first use.

**Worker roster** — the orchestrator loads its worker list from local profiles, not from the hub. It checks liveness via PID files. The hub is a message relay only, not a discovery service.

## Background Process Management

Agents can run as daemon/background processes:

- `kidecon start --name <n> --background` — spawns via `subprocess.Popen(start_new_session=True)`, writes PID to `~/.config/kidecon/agents/<n>.pid`, logs to `~/kidecon/logs/<n>.log`
- `kidecon agents stop --name <n>` — sends SIGTERM, waits 10s, then SIGKILL
- `kidecon agents status` — shows running/stopped state for all profiles
- `kidecon agents logs --name <n>` — tails the agent's log file

## Orchestrator Delegation

When the orchestrator receives a Discord DM:

1. ORIENT classifies the request (code, research, general, etc.)
2. PLAN step produces `{action: "delegate", params: {task, task_type}}`
3. `_dispatch_step("delegate")` loads the worker roster from profiles, selects the best online worker, sends an A2A `task_request` message to the worker, and responds to the user with "Working on it…"
4. The worker runs its full cognitive cycle and responds via A2A `task_result`
5. In a later poll cycle, the orchestrator receives the `task_result`, relays the result to the Discord user via the hub's bridge, and tracks the pending delegation in `pending_delegations`

**A2A message types** (FIPA ACL-derived):
- `task_request` — orchestrator → worker
- `task_result` — worker → orchestrator
- `task_refuse` — worker → orchestrator
- `task_failure` — worker → orchestrator

## Safety Boundaries

- **Tool gate** (`kidecon.yaml` `tool_gate`): `allow` / `deny` / `require_approval` lists gate every tool invocation.
- **Workspace scoping**: `wrappers/tools.py` resolves paths and rejects anything escaping `~/kidecon/workspace`.
- **Sandbox isolation**: scripts run in `~/kidecon/user_scripts/` only, 60s timeout, no shell interpolation, args passed as a list.
- **Discord safety firewall**: all `source: discord` messages pass through synchronous ingress and egress safety checks in `wrappers/safety_firewall.py` before Hermes processes or dispatches them.

## Shared LLM Library

`shared/llm_clients/` is a **vendored copy** from `kidecon-hub`. The canonical source lives in the hub repo. The sync direction is strictly one-way: **hub → agent**.

```
kidecon-hub/shared/llm_clients/  ←  CANONICAL. Edit here.
        │
        └── make sync-llm ──→  kidecon-agent/shared/llm_clients/  ←  READ-ONLY COPY
```

**DO NOT EDIT the agent copy.** Agent engineers who discover a bug or need to add a provider must:
1. Go to `kidecon-hub/shared/llm_clients/`
2. Make the change there
3. Run `make sync-llm` in the hub (or `make sync-llm` in the agent to pull)
4. Run `make check-llm-sync` to verify both repos match
