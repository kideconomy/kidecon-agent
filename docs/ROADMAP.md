# Roadmap

**Status:** Implementation-Ready
**Date:** 2026-07-04
**Repo:** `/home/solvire/Documents/projects/kidecon/source/kidecon-agent/`
**Stack:** Python 3.11 + httpx + keyring + PyYAML + Click CLI + bash install script

---

## Overview
KidEconomy Agent is the user-facing, public repo. A thin CLI wrapper and Python library that installs Hermes (from Nous Research), places KidEconomy config, registers the agent with the hub, and provides approved local tools + a sandboxed user-script executor. No database, no server — it's a client sidecar.

## Completed Phases
*None — this is the bootstrap session.*

## Planned & In-Progress Work

### Phase 0 — Foundation
**Category:** Infrastructure, Tooling, Git

| # | Item | Priority |
|---|------|----------|
| 0a | `git init`, `.gitignore`, `.editorconfig` (copy kidecon's verbatim) | Critical |
| 0b | `pyproject.toml` — ruff (kidecon's rules minus `DJ`, target py311), pytest | Critical |
| 0c | `.kilo/` — kilo.jsonc, 2 agent directives (architect, reviewer-safety) | Critical |
| 0d | `requirements.txt` — httpx, keyring, pyyaml, click | Critical |

### Phase 1 — Config & Hub Client
**Category:** Core Library

| # | Item | Priority |
|---|------|----------|
| 1a | `kidecon.yaml` — default config (provider, hub_url, tool_gate, update_channel) | Critical |
| 1b | `wrappers/__init__.py` | High |
| 1c | `wrappers/hub_client.py` — HubClient class: register(), hub_call(), poll_messages(), publish_skill() | Critical |
| 1d | `wrappers/tools.py` — approved local tools (file_read, file_append_markdown, message_user) | High |

### Phase 2 — Sandbox
**Category:** Core Library

| # | Item | Priority |
|---|------|----------|
| 2a | `wrappers/sandbox.py` — UserScriptSandbox: execute(script_name, args), isolated subprocess, 60s timeout, first-run approval gate | Medium |

### Phase 3 — CLI
**Category:** CLI

| # | Item | Priority |
|---|------|----------|
| 3a | `cli/__init__.py` | High |
| 3b | `cli/kidecon.py` — Click CLI: setup, start, stop, status, update, key add, key list, tier, skills list, skills browse | Critical |

### Phase 4 — Install Script
**Category:** Bootstrap

| # | Item | Priority |
|---|------|----------|
| 4a | `install.sh` — installs Hermes, places kidecon.yaml, prompts for OpenRouter key → keyring, registers agent → JWT → keyring | Critical |

### Phase 5 — Skills
**Category:** Skills

| # | Item | Priority |
|---|------|----------|
| 5a | `skills/.gitkeep` — placeholder for community-contributed starter skills | Low |
| 5b | `skills/README.md` — format guide for contributors | Low |

### Phase 6 — Documentation
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
