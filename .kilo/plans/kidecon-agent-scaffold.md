# Plan: Scaffold kidecon-agent Repository

**Status:** Implementation-Ready
**Date:** 2026-07-04
**Repo:** `/home/solvire/Documents/projects/kidecon/source/kidecon-agent/`
**Stack:** Python 3.11 + httpx + keyring + PyYAML + Click CLI + bash install script

---

## ROADMAP

### Overview
KidEconomy Agent is the user-facing, public repo. A thin CLI wrapper and Python library that installs Hermes (from Nous Research), places KidEconomy config, registers the agent with the hub, and provides approved local tools + a sandboxed user-script executor. No database, no server — it's a client sidecar.

### Completed Phases
*None — this is the bootstrap session.*

### Planned & In-Progress Work

#### Phase 0 — Foundation
**Category:** Infrastructure, Tooling, Git

| # | Item | Priority |
|---|------|----------|
| 0a | `git init`, `.gitignore`, `.editorconfig` (copy kidecon's verbatim) | Critical |
| 0b | `pyproject.toml` — ruff (kidecon's rules minus `DJ`, target py311), pytest | Critical |
| 0c | `.kilo/` — kilo.jsonc, 2 agent directives (architect, reviewer-safety) | Critical |
| 0d | `requirements.txt` — httpx, keyring, pyyaml, click | Critical |

#### Phase 1 — Config & Hub Client
**Category:** Core Library

| # | Item | Priority |
|---|------|----------|
| 1a | `kidecon.yaml` — default config (provider, hub_url, tool_gate, update_channel) | Critical |
| 1b | `wrappers/__init__.py` | High |
| 1c | `wrappers/hub_client.py` — HubClient class: register(), hub_call(), poll_messages(), publish_skill() | Critical |
| 1d | `wrappers/tools.py` — approved local tools (file_read, file_append_markdown, message_user) | High |

#### Phase 2 — Sandbox
**Category:** Core Library

| # | Item | Priority |
|---|------|----------|
| 2a | `wrappers/sandbox.py` — UserScriptSandbox: execute(script_name, args), isolated subprocess, 60s timeout, first-run approval gate | Medium |

#### Phase 3 — CLI
**Category:** CLI

| # | Item | Priority |
|---|------|----------|
| 3a | `cli/__init__.py` | High |
| 3b | `cli/kidecon.py` — Click CLI: setup, start, stop, status, update, key add, key list, tier, skills list, skills browse | Critical |

#### Phase 4 — Install Script
**Category:** Bootstrap

| # | Item | Priority |
|---|------|----------|
| 4a | `install.sh` — installs Hermes, places kidecon.yaml, prompts for OpenRouter key → keyring, registers agent → JWT → keyring | Critical |

#### Phase 5 — Skills
**Category:** Skills

| # | Item | Priority |
|---|------|----------|
| 5a | `skills/.gitkeep` — placeholder for community-contributed starter skills | Low |
| 5b | `skills/README.md` — format guide for contributors | Low |

#### Phase 6 — Documentation
**Category:** Documentation

| # | Item | Priority |
|---|------|----------|
| 6a | `AGENTS.md` — working constitution for AI agents (kidecon's format, CLI/wrapper-specific) | Critical |
| 6b | `docs/ARCHITECTURE.md` — client topology, wrapper responsibilities, hub communication | Critical |
| 6c | `docs/ROADMAP.md` — this file | Critical |
| 6d | `docs/ONBOARDING.md` — install + setup walkthrough | High |
| 6e | `docs/checkpoints/` — empty dir for future milestones | Low |
| 6f | `README.md` — public-facing readme with install instructions | High |

---

## Implementation Order

### Phase 0: Foundation
1. `git init` in `/home/solvire/Documents/projects/kidecon/source/kidecon-agent/`
2. Write `.gitignore` — Python template, add `.venv/`, `*.key`, `user_scripts/`
3. Write `.editorconfig` — copy kidecon's verbatim
4. Write `pyproject.toml` — see "Pyproject Config" below
5. Write `requirements.txt` — see "Requirements" below
6. Write `.kilo/kilo.jsonc` — adapted from kidecon's
7. Write `.kilo/agent/architect.md` — adapted (drop Django refs, point at wrapper/CLI structure)
8. Write `.kilo/agent/reviewer-safety.md` — adapted (keep secrets/keyring/injection checks, drop kid-safety, guide-module)
9. Write `.kilo/command/review.md` — adapted to invoke kidecon-agent's reviewer

### Phase 1: Config & Hub Client
10. Write `kidecon.yaml` — see "Default Config" below
11. Write `wrappers/__init__.py` — `import logging; logger = logging.getLogger(__name__)`
12. Write `wrappers/hub_client.py` — see "HubClient" below
13. Write `wrappers/tools.py` — see "Local Tools" below

### Phase 2: Sandbox
14. Write `wrappers/sandbox.py` — see "Sandbox" below

### Phase 3: CLI
15. Write `cli/__init__.py` — `import logging; logger = logging.getLogger(__name__)`
16. Write `cli/kidecon.py` — see "CLI" below

### Phase 4: Install Script
17. Write `install.sh` — see "Install Script" below

### Phase 5: Skills
18. Write `skills/.gitkeep`
19. Write `skills/README.md` — format guide

### Phase 6: Documentation
20. Write `AGENTS.md` — see "AGENTS.md Template" below
21. Write `docs/ARCHITECTURE.md` — client topology
22. Write `docs/ROADMAP.md` — this ROADMAP as standalone file
23. Write `docs/ONBOARDING.md` — install walkthrough
24. Write `README.md` — public-facing readme
25. Create `docs/checkpoints/` directory

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| CLI framework | Click | Mature, well-documented, clean subcommand structure |
| HTTP client | httpx | Async-capable, modern, works with FastAPI ecosystem |
| Secret storage | keyring (OS-native) | Cross-platform, secure, no plaintext secrets on disk |
| Config format | YAML (kidecon.yaml) | Human-readable, per spec |
| Python | 3.11 | Consistent with kidecon-hub |
| Hermes install | pip install from git (stubbed) | Nous Research repo URL is a placeholder — real URL TBD |
| No pre-commit | Skipped | Thin repo, minimal Python. Add later if needed. |
| No mypy | Skipped | Thin repo. Add later if needed. |
| Agent directives | architect + reviewer-safety only | No DB, no server, no surgeon/qa needed |

---

## Default Config (`kidecon.yaml`)

```yaml
provider: openrouter
hub_url: http://localhost:8000
tool_gate:
  allow:
    - file_read
    - file_append_markdown
    - hub_call
    - user_script_execute
    - message_user
  deny:
    - file_write_binary
    - shell_execute
    - file_delete
  require_approval:
    - user_script_first_run
    - hub_collaboration_request
update_channel: stable
hermes_version: v1.2.0
```

Note: `hub_url` defaults to `http://localhost:8000` for local dev. Production users change to `https://hub.kidecon.io`.

---

## HubClient (`wrappers/hub_client.py`)

```python
import logging
import uuid
import httpx
import keyring

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "kidecon-agent"
KEY_JWT = "hub_jwt"
KEY_AGENT_ID = "agent_id"


class HubClient:
    def __init__(self, hub_url: str = "http://localhost:8000"):
        self.hub_url = hub_url.rstrip("/")
        self.agent_id = self._get_or_create_agent_id()
        self.jwt = self._get_jwt()

    def _get_or_create_agent_id(self) -> str:
        agent_id = keyring.get_password(KEYRING_SERVICE, KEY_AGENT_ID)
        if not agent_id:
            agent_id = str(uuid.uuid4())
            keyring.set_password(KEYRING_SERVICE, KEY_AGENT_ID, agent_id)
        return agent_id

    def _get_jwt(self) -> str | None:
        return keyring.get_password(KEYRING_SERVICE, KEY_JWT)

    def register(self, name: str, platform: str = "cli") -> str:
        response = httpx.post(
            f"{self.hub_url}/api/register_agent",
            json={"agent_id": self.agent_id, "name": name, "platform": platform},
        )
        response.raise_for_status()
        data = response.json()
        self.jwt = data["jwt"]
        keyring.set_password(KEYRING_SERVICE, KEY_JWT, self.jwt)
        return self.jwt

    def _auth_headers(self) -> dict:
        if not self.jwt:
            raise RuntimeError("Not registered. Run `kidecon setup` first.")
        return {"Authorization": f"Bearer {self.jwt}"}

    def hub_call(self, tool_name: str, params: dict) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/mcp/call",
            json={"tool_name": tool_name, "params": params},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def poll_messages(self) -> list[dict]:
        response = httpx.get(
            f"{self.hub_url}/api/messages/poll",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("messages", [])

    def respond_to_message(self, message_id: str, accepted: bool, result: dict | None = None, reason: str | None = None) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/messages/{message_id}/respond",
            json={"accepted": accepted, "result": result, "reason": reason},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def send_message(self, to_agent_id: str, msg_type: str, payload: dict, reply_to: str | None = None) -> dict:
        response = httpx.post(
            f"{self.hub_url}/api/messages/send",
            json={"to_agent_id": to_agent_id, "type": msg_type, "payload": payload, "reply_to": reply_to},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def publish_skill(self, skill_card: dict) -> bool:
        # Stub — hub skill submission endpoint TBD
        logger.info("Publishing skill: %s", skill_card.get("name", "unknown"))
        return True

    def discover_skills(self, query: str) -> list[dict]:
        response = httpx.get(
            f"{self.hub_url}/api/skills/discover",
            params={"q": query},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("skills", [])

    def get_tier(self) -> int:
        response = httpx.get(
            f"{self.hub_url}/api/agent/{self.agent_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("tier", 1)
```

---

## Local Tools (`wrappers/tools.py`)

```python
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_BASE_DIR = Path.home() / "kidecon" / "workspace"


def file_read(file_path: str) -> str:
    target = (ALLOWED_BASE_DIR / file_path).resolve()
    if not str(target).startswith(str(ALLOWED_BASE_DIR)):
        raise PermissionError(f"Access denied: {file_path} outside workspace")
    return target.read_text()


def file_append_markdown(file_path: str, content: str) -> bool:
    target = (ALLOWED_BASE_DIR / file_path).resolve()
    if not str(target).startswith(str(ALLOWED_BASE_DIR)):
        raise PermissionError(f"Access denied: {file_path} outside workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.write(content + "\n")
    return True


def message_user(message: str) -> bool:
    # Stub — integration with Discord/Hermes messaging TBD
    logger.info("Message to user: %s", message)
    print(message)
    return True
```

---

## Sandbox (`wrappers/sandbox.py`)

```python
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path.home() / "kidecon" / "user_scripts"
TIMEOUT_SECONDS = 60
APPROVED_FILE = Path.home() / "kidecon" / ".approved_scripts"


class UserScriptSandbox:
    def __init__(self):
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        APPROVED_FILE.touch()

    def _is_approved(self, script_name: str) -> bool:
        approved = APPROVED_FILE.read_text().splitlines()
        return script_name in approved

    def _approve(self, script_name: str) -> None:
        approved = APPROVED_FILE.read_text().splitlines()
        if script_name not in approved:
            with APPROVED_FILE.open("a") as f:
                f.write(script_name + "\n")

    def execute(self, script_name: str, args: list[str] | None = None, auto_approve: bool = False) -> dict:
        script_path = SCRIPTS_DIR / f"{script_name}.py"
        if not script_path.exists():
            return {"error": f"Script not found: {script_name}"}

        if not self._is_approved(script_name):
            if not auto_approve:
                return {"error": "First run requires approval", "requires_approval": True}
            self._approve(script_name)

        cmd = ["python", str(script_path), *(args or [])]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                cwd=str(SCRIPTS_DIR),
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Script timed out after {TIMEOUT_SECONDS}s"}
```

---

## CLI (`cli/kidecon.py`)

Uses Click for subcommands. Each command calls into HubClient or wrappers.

```python
import logging
import subprocess
import sys
import yaml

import click
import keyring

from wrappers.hub_client import HubClient, KEYRING_SERVICE, KEY_JWT, KEY_AGENT_ID
from wrappers.sandbox import UserScriptSandbox

logger = logging.getLogger(__name__)

CONFIG_PATH = "kidecon.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@click.group()
def cli():
    """KidEconomy Agent CLI — lifecycle management for your KidEconomy agent."""


@cli.command()
@click.option("--name", prompt="Agent name", help="Name for this agent")
def setup(name):
    """First-time install: keyring, registration with hub."""
    config = load_config()
    client = HubClient(hub_url=config["hub_url"])
    jwt = client.register(name=name, platform="cli")
    click.echo(f"Agent registered. JWT stored in keyring.")
    click.echo(f"Agent ID: {client.agent_id}")


@cli.command()
def start():
    """Launch Hermes with KidEconomy config."""
    click.echo("Starting Hermes... (stub — Hermes integration TBD)")
    # Actual: subprocess.Popen(["hermes", "--config", "kidecon.yaml"])


@cli.command()
def stop():
    """Graceful shutdown of the agent."""
    click.echo("Stopping agent... (stub)")


@cli.command()
def status():
    """Check if agent is running and connected to hub."""
    try:
        config = load_config()
        client = HubClient(hub_url=config["hub_url"])
        tier = client.get_tier()
        jwt = keyring.get_password(KEYRING_SERVICE, KEY_JWT)
        agent_id = keyring.get_password(KEYRING_SERVICE, KEY_AGENT_ID)
        click.echo(f"Agent ID: {agent_id}")
        click.echo(f"Registered: {'yes' if jwt else 'no'}")
        click.echo(f"Tier: {tier}")
    except Exception as e:
        click.echo(f"Not connected: {e}")


@cli.command()
def update():
    """Pull latest Hermes + KidEconomy config."""
    click.echo("Checking for updates... (stub)")
    # Actual: re-run install.sh with latest version tag


@cli.group()
def key():
    """Manage API keys in keyring."""


@key.command("add")
@click.option("--name", prompt="Key name (e.g. openrouter)", help="Name of the API key")
@click.option("--value", prompt="API key value", hide_input=True, help="The API key")
def key_add(name, value):
    keyring.set_password(KEYRING_SERVICE, f"api_key_{name}", value)
    click.echo(f"Key '{name}' stored.")


@key.command("list")
def key_list():
    # keyring doesn't enumerate easily; show known keys
    known = ["openrouter", "hub_jwt", "agent_id"]
    for k in known:
        v = keyring.get_password(KEYRING_SERVICE, k if k.startswith("api_key_") else k)
        masked = f"{v[:4]}...{v[-4:]}" if v and len(v) > 8 else ("***" if v else "(not set)")
        click.echo(f"  {k}: {masked}")


@cli.command()
def tier():
    """Show current capability tier."""
    config = load_config()
    client = HubClient(hub_url=config["hub_url"])
    click.echo(f"Current tier: {client.get_tier()}")


@cli.group()
def skills():
    """Manage installed skills."""


@skills.command("list")
def skills_list():
    """Show installed skills."""
    click.echo("Installed skills: (none yet)")


@skills.command("browse")
@click.argument("query", required=False)
def skills_browse(query):
    """Query hub skill directory."""
    config = load_config()
    client = HubClient(hub_url=config["hub_url"])
    results = client.discover_skills(query or "")
    if not results:
        click.echo("No skills found.")
    for skill in results:
        click.echo(f"  {skill['name']} v{skill['version']} [{skill.get('category', 'uncategorized')}]")


if __name__ == "__main__":
    cli()
```

---

## Install Script (`install.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

# KidEconomy Agent Bootstrap Script
# Installs Hermes, places config, registers agent with hub

HERMES_VERSION="v1.2.0"
HERMES_REPO="https://github.com/Nous-Research/hermes"  # placeholder — real repo TBD
CONFIG_DIR="${HOME}/.config/kidecon"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== KidEconomy Agent Installer ==="

# 1. Check Python
if ! command -v python3.11 &>/dev/null; then
    echo "Error: Python 3.11 not found. Install it first."
    exit 1
fi

# 2. Create venv
VENV_DIR="${SCRIPT_DIR}/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3.11 -m venv "$VENV_DIR"
fi
source "$VENV/bin/activate"

# 3. Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r "${SCRIPT_DIR}/requirements.txt"

# 4. Place config
mkdir -p "$CONFIG_DIR"
cp "${SCRIPT_DIR}/kidecon.yaml" "${CONFIG_DIR}/kidecon.yaml"
echo "Config placed at ${CONFIG_DIR}/kidecon.yaml"

# 5. Prompt for OpenRouter API key
echo ""
echo "OpenRouter API key (leave blank to skip, add later with 'kidecon key add'):"
read -s -p "  Key: " OPENROUTER_KEY
echo ""
if [ -n "$OPENROUTER_KEY" ]; then
    python -c "import keyring; keyring.set_password('kidecon-agent', 'api_key_openrouter', '${OPENROUTER_KEY}')"
    echo "OpenRouter key stored in keyring."
fi

# 6. Install Hermes (stub — actual install method TBD)
echo ""
echo "Installing Hermes ${HERMES_VERSION}..."
# pip install "git+${HERMES_REPO}@${HERMES_VERSION}"
echo "  (stub — Hermes installation method TBD)"

# 7. Register agent with hub
echo ""
read -p "Enter a name for your agent: " AGENT_NAME
echo "Registering with hub..."
python "${SCRIPT_DIR}/cli/kidecon.py" setup --name "$AGENT_NAME"

echo ""
echo "=== Setup complete ==="
echo "Run 'kidecon start' to launch your agent."
echo "Connect via Discord: (link TBD)"
```

---

## Requirements (`requirements.txt`)

```
httpx>=0.27.0
keyring>=25.0.0
pyyaml>=6.0
click>=8.1.0
ruff>=0.6.0
pytest>=8.0.0
```

---

## Pyproject Config (`pyproject.toml`)

```toml
[tool.ruff]
target-version = "py311"
extend-exclude = [".venv/*"]

[tool.ruff.lint]
select = [
    "F", "E", "W", "C90", "I", "N", "UP", "YTT", "ASYNC", "S", "BLE",
    "FBT", "B", "A", "COM", "C4", "DTZ", "T10", "EM", "EXE", "FA",
    "ISC", "ICN", "G", "INP", "PIE", "T20", "PYI", "PT", "Q", "RSE",
    "RET", "SLF", "SLOT", "SIM", "TID", "TCH", "INT", "PTH", "ERA",
    "PD", "PGH", "PL", "TRY", "FLY", "PERF", "RUF",
]
ignore = ["S101", "RUF012", "SIM102", "UP038", "T201"]

[tool.ruff.lint.isort]
force-single-line = true

[tool.pytest.ini_options]
minversion = "8.0"
python_files = ["test_*.py"]
```

---

## AGENTS.md Template

```markdown
# AGENTS.md — KidEconomy Agent Working Constitution

Read at the start of every session. Canonical source of truth for stack, conventions, and safety rules.

## 1. Stack
- **Core:** Python 3.11, Click CLI, httpx, keyring, PyYAML.
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

## 4. Testing Discipline
- pytest with simple unit tests for wrappers and CLI.
- Mock httpx responses for hub_client tests.
- Test sandbox permission enforcement.

## 5. Review
- After non-trivial changes, run `/review` — invokes `reviewer-safety`.
```

---

## Validation Checklist

After all phases implemented:

1. `git init` has run, `.gitignore` is populated
2. `python cli/kidecon.py --help` shows all subcommands (setup, start, stop, status, update, key, tier, skills)
3. `python cli/kidecon.py setup --name test-agent` — prompts, registers with hub (if hub running at localhost:8000), stores JWT in keyring
4. `python cli/kidecon.py status` — shows agent ID, registration status, tier
5. `python cli/kidecon.py key add` — stores a key in keyring
6. `python cli/kidecon.py key list` — shows masked keys
7. `bash install.sh` — runs without errors (with stubs for Hermes install)
8. `ruff check .` passes
9. `python -m pytest tests/ -v` passes (if tests written)
10. `kidecon.yaml` is valid YAML and parseable by `yaml.safe_load`
