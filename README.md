# KidEconomy Agent

The user-facing client for the KidEconomy network: a thin CLI + Python library that installs Hermes (from Nous Research), places the KidEconomy config, registers your agent with the hub, and provides approved local tools plus a sandboxed user-script executor. **No server, no database** — it's a client sidecar.

## What it does

- **`install.sh`** — one-command bootstrap: venv, deps, config placement, keyring setup, hub registration.
- **`kidecon` CLI** — lifecycle management: `setup`, `start`, `stop`, `status`, `update`, `key`, `tier`, `skills`.
- **Wrappers** — `HubClient` (hub HTTP API), `tools` (workspace-scoped local tools), `UserScriptSandbox` (isolated subprocess execution with a 60s timeout and first-run approval).
- **Secrets in keyring** — API keys and the hub JWT are stored in the OS keyring, never on disk.

## Quick start

```bash
git clone <repo-url> kidecon-agent
cd kidecon-agent
bash install.sh
```

Prerequisites: **Python 3.14** (`python3.14` on PATH) and a reachable **kidecon-hub** (default `http://localhost:8000`; change `hub_url` in `kidecon.yaml` for production).

## CLI

```bash
python cli/kidecon.py --help
python cli/kidecon.py setup --name my-agent      # register with hub → JWT in keyring
python cli/kidecon.py status                     # agent id, registration, tier
python cli/kidecon.py key add                    # store an API key in keyring
python cli/kidecon.py key list                   # masked key listing
python cli/kidecon.py tier                       # current capability tier
python cli/kidecon.py skills list                # installed skills
python cli/kidecon.py skills browse <query>      # query the hub skill directory
python cli/kidecon.py start                      # launch Hermes (stubbed)
```

## Layout

```mermaid
flowchart TD
    root["kidecon-agent/"]
    root --> install["install.sh  # bootstrap script"]
    root --> kyaml["kidecon.yaml  # default config (provider, hub_url, tool_gate, ...)"]
    root --> reqs["requirements.txt"]
    root --> pyproj["pyproject.toml  # ruff (py311) + pytest"]
    root --> cli["cli/"]
    cli --> cliinit["__init__.py"]
    cli --> clicli["kidecon.py  # Click CLI"]
    root --> wrappers["wrappers/"]
    wrappers --> wrinit["__init__.py"]
    wrappers --> hubclient["hub_client.py  # HubClient -- hub HTTP API"]
    wrappers --> tools["tools.py  # file_read, file_append_markdown, message_user"]
    wrappers --> sandbox["sandbox.py  # UserScriptSandbox"]
    root --> skills["skills/  # community-contributed starter skills"]
    root --> docs["docs/"]
    docs --> docsarch["ARCHITECTURE.md"]
    docs --> docsroad["ROADMAP.md"]
    docs --> docsonb["ONBOARDING.md"]
    docs --> docsckpt["checkpoints/"]
    root --> agentsmd["AGENTS.md  # working constitution for AI agents"]
    root --> kilo[".kilo/  # Kilo agent directives + config"]
```

## Docs

- [Onboarding](docs/ONBOARDING.md) — install + setup walkthrough.
- [Architecture](docs/ARCHITECTURE.md) — client topology and component responsibilities.
- [Roadmap](docs/ROADMAP.md) — phased plan.
- [AGENTS.md](AGENTS.md) — working constitution for AI agents editing this repo.

## Notes

- Hermes installation is currently **stubbed** — the real Nous Research repo URL is TBD.
- The hub skill-submission endpoint is TBD; `publish_skill` is a stub.
