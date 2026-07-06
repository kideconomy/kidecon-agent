# Onboarding

A walkthrough for installing and setting up the KidEconomy Agent from scratch.

## Prerequisites

- **Python 3.14** on PATH as `python3.14`.
- A running **kidecon-hub** at `http://localhost:8000` (for registration). For local dev the hub default URL is fine; for production set `hub_url: https://hub.kidecon.io` in `kidecon.yaml`.
- (Optional) An **OpenRouter API key**. You can skip and add it later.

## 1. Clone & install

```bash
git clone <repo-url> kidecon-agent
cd kidecon-agent
bash install.sh
```

`install.sh` will:
1. Create a `env/` and `pip install .` (installs the `kidecon` CLI command on PATH).
2. Copy `kidecon.yaml` to `~/.config/kidecon/kidecon.yaml`.
3. Prompt for your OpenRouter key (stored in the OS keyring; blank to skip).
4. Install Hermes (currently a stub -- the real install method is TBD).
5. Prompt for an agent name and register it with the hub, storing the JWT in keyring.

After install, the `kidecon` command is available inside the venv:

```bash
source env/bin/activate
kidecon --help
```

## 2. Makefile targets (dev convenience)

```bash
make help      # list all targets
make install   # pip install -e . (editable dev install)
make test      # run tests
make lint      # ruff check + format check
make format    # auto-fix with ruff
make clean     # remove caches and build artifacts
```

## 3. Add an API key (if you skipped the prompt)

```bash
kidecon key add
#   Key name (e.g. openrouter): openrouter
#   API key value: ********
```

Verify:

```bash
kidecon key list
```

## 4. Check status

```bash
kidecon status
```

Shows your agent ID, whether you are registered, and your current tier.

## 5. Start the agent

```bash
kidecon start
```

(Hermes launch is currently stubbed -- integration TBD.)

## 6. Skills

```bash
kidecon skills list         # installed skills (none yet)
kidecon skills browse       # query the hub skill directory
```

See `skills/README.md` for the skill format if you want to contribute one.

## Troubleshooting

- **`Not registered. Run 'kidecon setup' first.`** -- registration failed or was skipped. Re-run `kidecon setup --name <name>` with the hub running.
- **`Error: Python 3.14 not found.`** -- install Python 3.14 and ensure `python3.14` is on PATH.
- **Hub connection errors** -- confirm `kidecon.yaml` `hub_url` points at a reachable hub.

## Next

- Read `docs/ARCHITECTURE.md` for the component map.
- Read `docs/FLOW_CONTROL.md` for install/sandbox/message flow diagrams.
- Read `AGENTS.md` for the working constitution before editing code.
