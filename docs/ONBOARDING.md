# Onboarding

Walkthrough for installing and setting up the KidEconomy Agent from scratch on a
fresh machine — the "third-party user" box. The agent talks to a **hub** (managed
by your team). This doc uses the public hub at `https://hub.kidecon.me`.

## Prerequisites

- **Python 3.10+** (dev uses 3.12).
- **git**.
- A **KidEconomy** account and (optionally) an **OpenRouter API key**.
- For skills that touch GitHub docs: a read-only GitHub PAT (see step 8).

## 1. Install

```bash
git clone git@github.com:kideconomy/kidecon-agent.git
cd kidecon-agent
pip install -e .          # installs the `kidecon` CLI
```

## 2. Initialize

```bash
kidecon init
```

Writes `~/.config/kidecon/kidecon.yaml`. Defaults to the **public** hub:

```bash
grep -E "hub_url|safety:" ~/.config/kidecon/kidecon.yaml
# hub_url: https://hub.kidecon.me
# safety:  openai/gpt-4o-mini
```

> **Safety model is critical.** The `safety` field must be a model that supports
> OpenRouter structured JSON output (default `openai/gpt-4o-mini`). The safety
> firewall is **fail-closed** — if it can't verify a message, it blocks it. A dead
> or non-structured model makes *every* Discord DM return "Safety service unavailable".

For a local dev hub instead, pass it explicitly:

```bash
kidecon init --hub http://localhost:8000 --kideconomy-api http://localhost:8090
```

## 3. Add the OpenRouter key

The agent needs an OpenRouter key to think and to run the ingress/egress safety
check. Keys live only in the OS keyring, never on disk:

```bash
kidecon key add --name openrouter
kidecon key list
```

## 4. Authenticate with KidEconomy

```bash
kidecon authenticate
# KidEconomy username: <your-user>
# KidEconomy password: <hidden>
```

Authenticates you against the hub via KidEconomy SSO and provisions the user. If
your KidEconomy account is **staff**, agents you create inherit **staff / tier 3**,
which is required to use staff-only skills (e.g. `docs-mirror`, `min_hub_tier=3`).

## 5. Create an agent

```bash
kidecon agents create --name scratch --role standalone
```

Roles: `orchestrator | worker | standalone`.

Agent identity is **explicit** — there is no active-profile auto-pick:
- `--name` for `start` / `stop` / `status` (e.g. `kidecon status --name scratch`)
- `--agent` for hub-talking commands (e.g. `kidecon --agent scratch skills ...`)

Check what the hub provisioned (registration + tier):

```bash
kidecon status --name scratch
```

Staff-only skills are only visible/usable when the agent is tier 3. If the agent
isn't staff and needs to be, an existing staff admin grants it:
`kidecon --agent <admin> admin agents set_tier ...` (or your team's bootstrap admin).

## 6. Skills

Skills declare their tool surface (`definition.tools`) and the runtime enforces
it. Tool-bearing skills force the full plan/execute path so their tools actually
run (they are not just narrated).

```bash
kidecon --agent scratch skills discover                  # search the hub directory
kidecon --agent scratch skills mine                      # your submitted skills
kidecon --agent scratch skills submit --file ./skill.json
```

Staff (tier 3) admin flow to take a skill **live**:

```bash
kidecon --agent scratch admin skills pending
kidecon --agent scratch admin skills set-tier --id <skill-id> --tier 3
kidecon --agent scratch admin skills approve --id <skill-id>
```

`Skill.name` is globally unique; to replace one, staff delete then resubmit:
`kidecon --agent <admin> admin skills delete --id <skill-id>`.

## 7. Start the agent

```bash
kidecon start --name scratch --background
kidecon status --name scratch
```

## 8. Use it (Discord)

The hub embeds a Discord client (no separate bridge process). When the hub is
configured with a `DISCORD_BOT_TOKEN`, you **DM its app's bot** and the hub routes
the message to your agent. The agent self-verifies, matches a skill, and runs it —
e.g. DM "pull the docs" matches `docs-mirror`, whose `docs_sync` tool clones the
docs into the workspace.

For `docs-mirror` (staff-only) to actually sync, the machine needs:

```bash
# read-only GitHub PAT for the docs repo, stored in the keyring:
kidecon key add --name github-docs --value github_pat_...
```

and a `docs:` block (enabled, repo_url, branch, subfolder) in `kidecon.yaml`.

## Managing local state

```bash
kidecon stop --name scratch       # SIGTERM (-> SIGKILL) the daemon
kidecon restart --name scratch    # stop + start
kidecon panic --force             # ⚠ WIPES all profiles, config, and keys
```

## Troubleshooting

- **`Not registered. Run 'kidecon agents create' first.`** — create the agent.
- **`Safety service unavailable`** — the `safety` model is invalid; set one that
  supports structured output (e.g. `openai/gpt-4o-mini`) in `kidecon.yaml`.
- **Agent registered with a hashed/token "username" and tier 1** — the hub couldn't
  reach KidEconomy, so KE token verification failed open. A recent fix makes these
  registrations fall back to a deterministic `local:<name>` user instead of keying
  off the raw token (which minted duplicate users). For automatic staff detection,
  the hub `.env` must set `KIDECONOMY_API_URL` (and not disable verification).
- **`Access blocked by the hub ... (403)`** — read the `Reason`: disabled KE
  account, deactivated agent, or a re-link ownership conflict.
- **`JWT expired ... (401)`** — re-run `kidecon agents create` to rotate the JWT.
- **Hub connection errors** — confirm `hub_url` points at the reachable hub.

## Next

- `docs/ARCHITECTURE.md` — component map
- `docs/SAFETY.md` — safety model & firewall
- `docs/SKILL_AUTHORING.md` — authoring + submitting skills
- `AGENTS.md` — the working constitution
