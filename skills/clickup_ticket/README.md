# clickup-ticket

Creates internal ClickUp tickets for bugs and feature requests on behalf of
staff users.

## How it works

The agent holds the ClickUp API key in the OS keyring (set via
`kidecon key add --name clickup --value pk_xxx`). The key **never transits to
the hub** — the agent posts directly to the ClickUp API.

Flow:

1. Staff check — if not staff, route to `support.ticket` on the hub and exit.
2. Triage — classify as bug, feature, or support.
3. Gather details through conversation (repro steps, expected/actual, env).
4. Verify expected behavior via `kideconomy.verify_behavior` on the hub.
5. Fetch routing config from `tickets.meta` on the hub.
6. POST the ticket directly to ClickUp using the local API key.
7. Call `tickets.notify` on the hub to post the ticket link to #tech Discord.
8. Report the ClickUp ticket URL to the user.

## Setup

```bash
# 1. Get your ClickUp personal API token
#    https://app.clickup.com/settings → Apps → Personal API Token

# 2. Store it in the agent keyring
kidecon key add --name clickup --value pk_xxxx

# 3. Configure routing (optional — override in kidecon.yaml under skills.clickup-ticket)
#    The hub's tickets.meta tool provides list_map, team_id, default_assignees.
```

## Config

Routing config can be set in `kidecon.yaml` under `skills.clickup-ticket.config`
or fetched from the hub via `tickets.meta`. Hub config takes precedence.

## Key name

The ClickUp API key is read from keyring under the name `clickup`
(stored as `api_key_clickup` by `kidecon key add --name clickup`).
