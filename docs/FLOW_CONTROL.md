# System Flow Control & State Machines

## 1. Bootstrap: Install & Register

```mermaid
sequenceDiagram
    participant User
    participant Install as install.sh
    participant Venv as env
    Install->>Install: Check python3.14 available
    Install->>Venv: python3.14 -m venv env
    Install->>Venv: pip install -r requirements.txt
    Install->>Install: mkdir -p ~/.config/kidecon
    Install->>Install: cp kidecon.yaml ~/.config/kidecon/

    Install->>User: Prompt: OpenRouter API key?
    User-->>Install: (optional, can skip)
    alt Key provided
        Install->>Keyring: set_password(kidecon-agent, api_key_openrouter, key)
    end

    Note over Install: Hermes install -- currently stubbed

    Install->>User: Prompt: Agent name?
    User-->>Install: agent-name
    Install->>CLI: python cli/kidecon.py setup --name agent-name
    CLI->>CLI: Generate UUID if not in keyring (agent_id)
    CLI->>Hub: POST /api/register_agent {agent_id, name, platform: cli}
    Hub-->>CLI: 200 {jwt, agent_profile}
    CLI->>Keyring: set_password(kidecon-agent, hub_jwt, jwt)
    CLI->>Keyring: set_password(kidecon-agent, agent_id, agent_id)
    CLI-->>User: "Agent registered. Run 'kidecon start'"
```

- `agent_id` is a UUID generated once and persisted in the OS keyring.
- Registration is idempotent: re-running `setup` re-registers with the same agent_id.
- OpenRouter key is optional during install; can be added later via `kidecon key add`.

---

## 2. HubClient Request Flow

```mermaid
sequenceDiagram
    participant Caller as CLI / Hermes
    participant Client as wrappers/hub_client.py
    participant Keyring as OS Keyring
    participant Hub as kidecon-hub

    Caller->>Client: hub_call(tool_name, params)
    Client->>Keyring: get_password(kidecon-agent, hub_jwt)
    alt JWT exists
        Client->>Hub: POST /api/mcp/call {tool_name, params}
        Note over Hub: Tier check, telemetry, dispatch (see hub FLOW_CONTROL.md)
        Hub-->>Client: 200 {result, error}
        Client-->>Caller: return result
    else No JWT
        Client-->>Caller: raise RuntimeError("Not registered")
    end
```

### 2.1 HubClient: All Operations

```mermaid
flowchart LR
    subgraph HubClient
        register["register: POST /register_agent, store JWT in keyring"]
        hub_call["hub_call: POST /mcp/call with Bearer JWT"]
        poll["poll_messages: GET /messages/poll"]
        respond["respond_to_message: POST /messages/:id/respond"]
        send["send_message: POST /messages/send"]
        discover["discover_skills: GET /skills/discover"]
        get_tier["get_tier: GET /agent/:agent_id"]
    end

    register --> hub_call
    register --> poll
    register --> get_tier
```

- All authenticated operations read the JWT from keyring via `_auth_headers()`.
- If JWT is expired, the hub returns 401; the caller must re-run `register()`.

---

## 3. Message Poll & Respond Loop

```mermaid
sequenceDiagram
    participant Hermes
    participant Client as HubClient
    participant Hub as kidecon-hub
    participant User as Human (Discord)

    loop Poll interval
        Hermes->>Client: poll_messages()
        Client->>Hub: GET /api/messages/poll
        Hub-->>Client: {messages: [...]}
        Client-->>Hermes: list of unread messages

        alt Collaboration request
            Hermes->>User: "Bot B requests: check Sentry #12345. Approve?"
            User-->>Hermes: Approves

            Hermes->>Client: respond_to_message(id, accepted=true)
            Client->>Hub: POST /api/messages/{id}/respond
            Hub-->>Client: 200 {status: accepted}
        else Escalation
            Hermes->>User: "Issue Z unhandled by my human. Escalate?"
        else Discovery broadcast
            Hermes->>Hermes: Update local skill catalog
        end
    end
```

- Poll interval is determined by Hermes configuration.
- Messages are marked `delivered` on poll; they are not re-delivered.
- Unresponded messages remain in the DB with `delivered` status.

---

## 4. User Script Sandbox Execution

```mermaid
sequenceDiagram
    participant Agent
    participant Sandbox as UserScriptSandbox
    participant FS as ~/kidecon/user_scripts/
    participant Subproc as Subprocess (60s timeout)

    Agent->>Sandbox: execute(script_name, args)
    Sandbox->>FS: Check script exists
    alt Script not found
        Sandbox-->>Agent: {error: "Script not found"}
    end

    Sandbox->>FS: Read ~/kidecon/.approved_scripts
    alt Script NOT approved (first run)
        alt auto_approve = False
            Sandbox-->>Agent: {error: "First run requires approval", requires_approval: true}
        else auto_approve = True
            Sandbox->>FS: Append script_name to .approved_scripts
        end
    end

    Sandbox->>Subproc: python script_name.py [args...]
    Subproc->>Subproc: Runs in SCRIPTS_DIR, 60s timeout
    alt Success
        Subproc-->>Sandbox: {stdout, stderr, returncode}
    else Timeout
        Subproc-->>Sandbox: raise TimeoutExpired
        Sandbox-->>Agent: {error: "Script timed out after 60s"}
    end
    Sandbox-->>Agent: {stdout, stderr, returncode}
```

### 4.1 Local Tools (wrappers/tools.py)

```mermaid
flowchart TD
    subgraph LocalTools[Allowed Local Tools]
        FR[file_read: Read file from ~/kidecon/workspace/]
        FA[file_append_markdown: Append markdown to file]
        MU[message_user: Print message to stdout]
    end

    FR -->|Enforces| PB[Path boundary check: resolves to ~/kidecon/workspace/]
    FA -->|Enforces| PB
    MU -->|Stubbed| Discord[Discord integration TBD]
```

- `file_read` and `file_append_markdown` resolve and validate paths against `~/kidecon/workspace/`.
- Any path escaping the workspace boundary raises `PermissionError`.
- `message_user` is a stub; real implementation will route through Hermes/Discord.

---

## 5. Keyring & Secret Management

```mermaid
flowchart TD
    subgraph Keyring[OS Keyring -- kidecon-agent service]
        AGENT_ID[agent_id: UUID, generated once]
        HUB_JWT[hub_jwt: JWT from hub, rotated on re-register]
        API_KEYS[api_key_<name>: user-added API keys]
    end

    CLI[cli/kidecon.py] -->|key list| Keyring
    CLI -->|key add| Keyring
    HubClient -->|reads| Keyring
    HubClient -->|writes JWT| Keyring
    Install[install.sh] -->|writes OpenRouter key| Keyring

    HubClient -->|_get_or_create_agent_id| AGENT_ID
    HubClient -->|register sets hub_jwt| HUB_JWT
    CLI -->|key add openrouter| API_KEYS
```

- All secrets live in the OS keyring, never on disk.
- `kidecon.yaml` contains no secrets; it is safe to commit.
- `install.sh` prompts for the OpenRouter key interactively and stores it via keyring.
- `kidecon key add` lets users add additional API keys post-install.

---

## 6. CLI Command Dispatch

```mermaid
flowchart TD
    CLI_Entry["python cli/kidecon.py"] --> CMD{Subcommand}

    CMD -->|setup| Setup["HubClient.register(), store JWT in keyring"]
    CMD -->|start| Start["Launch Hermes with kidecon.yaml (stub)"]
    CMD -->|stop| Stop["Graceful shutdown (stub)"]
    CMD -->|update| Update["Re-run install.sh with latest version (stub)"]
    CMD -->|status| Status["HubClient.get_tier(), check keyring for JWT"]
    CMD -->|key add| KeyAdd["Store API key in keyring"]
    CMD -->|key list| KeyList["Show masked keys from keyring"]
    CMD -->|tier| Tier["HubClient.get_tier()"]
    CMD -->|skills list| SkillsList["Show installed skills from local skills/ dir"]
    CMD -->|skills browse| SkillsBrowse["HubClient.discover_skills(query)"]
```

- `load_config()` reads `kidecon.yaml` for `hub_url`.
- Commands marked `stub` are placeholders for Hermes integration.
- `skills browse` queries the hub's `/api/skills/discover` endpoint.

---

## 7. Tool Gate Configuration

The `kidecon.yaml` tool gate controls which tools Hermes is allowed to invoke:

```mermaid
flowchart TD
    Agent[Agent wants to call tool] --> Gate{Check tool_gate}

    Gate -->|In allow list| Execute[Execute tool]
    Gate -->|In deny list| Denied[Blocked: tool is denied]
    Gate -->|In require_approval| Approve{User approval?}
    Gate -->|Not in any list| Default[Default: allow?]

    Approve -->|Yes| Execute
    Approve -->|No| Denied
```

- `allow`: Tools always permitted (file_read, file_append_markdown, hub_call, user_script_execute, message_user).
- `deny`: Tools always blocked (file_write_binary, shell_execute, file_delete).
- `require_approval`: First-time use requires explicit user confirmation (user_script_first_run, hub_collaboration_request).
- The tool gate is enforced by Hermes using this config; the Python wrappers do not enforce it themselves.

---

## 8. Key Code Paths

| Flow | Entry Point | Key Files |
|------|------------|-----------|
| Install & bootstrap | `bash install.sh` | `install.sh`, `cli/kidecon.py::setup` |
| Agent registration | `HubClient.register()` | `wrappers/hub_client.py`, OS keyring |
| MCP tool call | `HubClient.hub_call()` | `wrappers/hub_client.py::_auth_headers()` |
| Message poll | `HubClient.poll_messages()` | `wrappers/hub_client.py` |
| Message respond | `HubClient.respond_to_message()` | `wrappers/hub_client.py` |
| Skill discovery | `HubClient.discover_skills()` | `wrappers/hub_client.py`, hub `/api/skills/discover` |
| User script execution | `UserScriptSandbox.execute()` | `wrappers/sandbox.py` |
| File read (local) | `file_read()` | `wrappers/tools.py` |
| File append (local) | `file_append_markdown()` | `wrappers/tools.py` |
| Key management | `kidecon key add/list` | `cli/kidecon.py`, OS keyring |
| Tier check | `HubClient.get_tier()` | `wrappers/hub_client.py`, hub `/api/agent/{id}` |
| Config loading | `load_config()` | `cli/kidecon.py`, `kidecon.yaml` |