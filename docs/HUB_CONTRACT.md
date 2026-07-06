# HUB_CONTRACT.md — `kidecon-agent` ↔ `kidecon-hub` HTTP Contract

**Status:** Living document. Versioned. Update when either side changes a surface.
**Owners:** `kidecon-agent` (edge consumer) and `kidecon-hub` (service provider).
**Scope:** This is the `kidecon-agent` view of the hub contract. It pins the surfaces the edge depends on so the hub cannot break the agent silently. The hub owns the endpoint implementations; the agent owns conformance to this file.

This contract is the formalization of the *de facto* integration documented in `docs/AGENT_NETWORK_REFERENCE.md` §1.3 and §2.2. Where this file and the reference disagree, **this file wins** for the surfaces listed here.

---

## 0. Stable facts

- **Transport:** HTTP/1.1, JSON bodies. **No WebSocket, no SSE, no push** in v0.x. The edge polls (§3). A WebSocket channel is a future surface (§6) and a scope expansion requiring a new contract version.
- **Auth:** stateless per-agent JWT (HS256). Bearer in `Authorization` header. The hub stores a per-agent `jwt_secret`; re-registering rotates it and invalidates prior tokens.
- **Identity on the edge:** the agent holds `agent_id` (UUID v4, self-generated) + `hub_jwt` (hub-issued) in the OS keyring (service `kidecon-agent`). The agent **never** holds a Discord token and **never** talks to `kidecon` core directly.
- **No server, no database on the edge:** all persistent state the agent reads/writes is local (`MEMORY.md`, `user_scripts/`, audit log, keyring). The hub is the only remote dependency.

---

## 1. Endpoint registry (v0.x — "de facto")

All paths are relative to `hub_url` (default `http://localhost:8000`; production `https://hub.kidecon.io`). All authenticated requests carry `Authorization: Bearer <jwt>`.

| # | Surface | Method + Path | Auth | Request body / params | Response (2xx) | Edge caller | Status |
|---|---------|---------------|------|------------------------|----------------|--------------|--------|
| R1 | Register / re-register | `POST /api/register_agent` | none | `{agent_id: str, name: str, platform: str}` | `{jwt: str, agent_profile: {...}}` | `HubClient.register()` | Live |
| R2 | Agent self-status | `GET /api/agent/{agent_id}` | Bearer | — | `{tier: int, status, ...}` | `HubClient.get_tier()` | Live |
| R3 | Set status (online/offline) | `PUT /api/agent/{agent_id}/status` | Bearer | `{status: "online"\|"offline"}` | `200` | *(not yet wired in edge)* | Live on hub |
| R4 | Deactivate / revoke JWT | `DELETE /api/agent/{agent_id}` | Bearer | — | `200`; rotates `jwt_secret` | *(uninstall path, US10)* | Live on hub |
| R5 | MCP tool call (tier-gated) | `POST /api/mcp/call` | Bearer | `{tool_name: str, params: dict}` | `{result: ..., error: ...}` | `HubClient.hub_call()` | Live (mock tools) |
| R6 | Poll messages | `GET /api/messages/poll` | Bearer | — | `{messages: [{id, from_agent_id, type, payload, reply_to, status}]}` | `HubClient.poll_messages()` | Live |
| R7 | Respond to message | `POST /api/messages/{message_id}/respond` | Bearer | `{accepted: bool, result: dict\|null, reason: str\|null}` | `{message_id, status}` | `HubClient.respond_to_message()` | Live |
| R8 | Send message | `POST /api/messages/send` | Bearer | `{to_agent_id: str, type: str, payload: dict, reply_to: str\|null}` | `{message_id, status}` | `HubClient.send_message()` | Live |
| R9 | Discover skills | `GET /api/skills/discover` | Bearer | `?q=<query>` | `{skills: [{id, name, version, category, description}]}` | `HubClient.discover_skills()` | Live (approved-only) |
| R10 | Skill detail | `GET /api/skills/{skill_id}` | Bearer | — | full skill definition (JSON) | *(not yet wired in edge)* | Live on hub |

**Status legend:** *Live* = implemented on both sides; *Live on hub* = hub implements it, edge does not yet call it; *(stub)* = edge method exists but is a no-op/print.

**Edge gaps to wire against existing hub endpoints:**
- R3 `PUT /status` — the edge must self-report `online` on start and `offline` on stop/shutdown, so hub staleness (`Agent.last_seen`) reflects reality. Feeds F1/F2 laptop-online detection (§3.8 of the reference).
- R10 `GET /api/skills/{id}` — needed before the edge can install a skill it discovered via R9.
- R4 `DELETE /api/agent/{id}` — the uninstall path (US10) must call this to revoke the hub JWT and rotate the secret.

---

## 2. Auth model — stateless per-agent JWT

1. **Registration (R1).** The edge POSTs its self-generated `agent_id` + a `name` + `platform="cli"`. The hub creates or updates the `Agent` row, generates a random `jwt_secret` (`secrets.token_hex(32)`), signs a JWT, returns it. The edge stores `jwt` in keyring under `hub_jwt`.
2. **Verification.** Every authenticated request: the hub's `get_current_agent` loads **all** agents and iterates `verify_jwt(token, agent.jwt_secret)` until one matches. **This is O(N) per request** (reference §1.3). Implication for the edge: a tight poll interval multiplies hub cost. Until the hub fixes this (its own decision, §8 #9), the edge **must not poll aggressively**. Default poll interval: 30s; `doctor` surfaces `last_seen` staleness.
3. **Expiry.** Hub JWT expires at `JWT_EXPIRE_MINUTES` (default 1440 = 24h). On expiry the edge gets 401. The edge must re-run `register()` (R1), which rotates the secret. `doctor` detects 401s and offers re-register (F11).
4. **No refresh tokens.** Re-registration is the only rotation path. The edge does not cache credentials beyond the keyring.
5. **Scope of the token.** The JWT identifies *this agent* to *the hub only*. It is not valid against `kidecon` core (DRF) or any other service. The edge must never present it elsewhere.

---

## 3. Polling semantics (the only transport in v0.x)

- The edge calls R6 (`GET /api/messages/poll`) on a loop. Default interval: **30s**. Tunable via `kidecon.yaml` (field TBD: `poll_interval_seconds`).
- A poll returns all messages where `to_agent_id == this_agent AND status == "pending"`. The hub **immediately marks them `status="delivered"`** in the same request.
- **Delivery is destructive-by-status:** unresponded messages stay `delivered` and are **never re-delivered** on subsequent polls. The edge is the only thing that surfaces them. If the laptop is off, work waits silently in the hub DB.
- The edge **must** respond to every `delivered` message via R7 (`POST /{id}/respond`) with `accepted: true|false` + optional `result`/`reason`. Dropping a message without responding leaves it permanently `delivered` and invisible to future polls.
- No mid-turn push: a second turn arriving while the edge processes the first waits for the next poll.
- **Laptop-online signal** is inferred from `Agent.last_seen` recency, updated on every poll/call. There is no heartbeat and no persistent connection in v0.x.

**Consequence the edge owns:** because polling is the only channel, any "real-time" UX (slash-command-to-laptop race, F4) is **not viable under v0.x** without a fallback to F1/F2 (hub-side read / honest offline). This is the strongest argument for the future WebSocket surface (§6).

---

## 4. MCP tool call contract (R5)

- Request: `{tool_name: str, params: dict}`. The hub applies tier gating (`check_tool_access`) and writes a `Telemetry` row (`tool_called`, `timestamp`).
- Response (always 2xx, even on tool failure): `{result: <data|null>, error: <str|null>}`. **Tool errors are not HTTP errors** — they are `200` with `error` set. The edge must check `error` before trusting `result`.
- Tool availability is hub-side and tier-gated; the edge's `kidecon.yaml` `tool_gate` is a **local** allow/deny/require_approval list on top — it can only *restrict further*, never *expand* what the hub allows.
- `Telemetry.domains_accessed` (JSON) exists on the hub but is **never populated** today (reference §4.6). The edge does not yet push domains. See §5 (missing surfaces).

---

## 5. Missing surfaces (v0.x gaps — require a contract bump to v0.y or v1)

These are referenced in the reference but **do not exist** on the hub. Adding any of them is a **breaking contract change** requiring both sides to ship and this file to version up.

| # | Surface | Why the edge needs it | Blocking |
|---|---------|----------------------|----------|
| M1 | Telemetry push — domains contacted | Privacy posture (§4.6): edge must report domains `user_scripts/` touched so `Telemetry.domains_accessed` is populated. Without it, "telemetry over surveillance" is undeliverable. | Phase 4 |
| M2 | Dreaming summary push | Nightly summary the laptop *chooses* to push; hub stores it; the 7am digest (F6) is built from it. Hub never reads raw `MEMORY.md`. | Phase 4 |
| M3 | WebSocket push channel | Sub-second push, mid-turn delivery, F4 viability. Conflicts with "no server" only superficially (edge dials out). | Phase 2 (decided: not in Phase 0/1, §8 #1) |
| M4 | Hub-side content-filter hook | Kid-safety (§4.5, decided: learners are children and may run the agent). Edge needs a seam to route kid-facing outputs through a hub-side filter. | Phase 1 (sandbox phase) |

---

## 6. Future WebSocket surface (out of v0.x scope)

If adopted (decided deferred to Phase 2, §8 #1), the contract becomes:
- Edge dials `WSS {hub_url}/edge/{session_id}` with the Bearer JWT.
- Hub pushes turns down; edge ACKs receipt, later POSTs the result via R7 (or a WS reply frame).
- `Agent.status`/`last_seen` driven by a heartbeat (2 missed pings → offline), not by poll recency.
- F7 (reconnect/backoff) becomes real; under polling it is moot.

This is a **v1.0** contract change. The edge will keep the polling client as the fallback path even after WS lands (laptop-sleep resilience).

---

## 7. Change protocol

1. **Hub changes an endpoint shape** (path, body field, 2xx response field, or auth model) → hub bumps this contract's version and **must not** ship until the edge conforms, unless the change is backward-compatible (additive field). Breaking field removals/renames require a coordinated release.
2. **Edge adds a caller** for an existing hub endpoint (e.g. wiring R3/R4/R10) → no contract bump; edge-only change.
3. **Adding a missing surface (§5)** → new contract version; both sides ship together.
4. **Poll interval / telemetry defaults** → tunable in `kidecon.yaml`, not a contract change.
5. Any change to this file must update the `Version` and `Last updated` below and cross-reference the `docs/AGENT_NETWORK_REFERENCE.md` section it realizes.

---

## 8. Edge conformance checklist (what `kidecon-agent` must guarantee to the hub)

- [ ] Presents `Authorization: Bearer <jwt>` on every authenticated call (R2–R10).
- [ ] Never sends the JWT to any host other than `hub_url`.
- [ ] Calls R3 `PUT /status` online on `start`, offline on `stop`/shutdown.
- [ ] Responds to **every** polled message via R7; never leaves a `delivered` message unresponded.
- [ ] Treats R5 responses as `200 + {result, error}`; checks `error` before trusting `result`.
- [ ] Default poll interval ≥ 30s (hub auth is O(N) per request, §2).
- [ ] On 401: re-registers via R1 (rotates secret); surfaces via `doctor`.
- [ ] Uninstall path calls R4 `DELETE /api/agent/{id}` to revoke the JWT (US10).
- [ ] Never imports `kidecon` or `kidecon-pm`; depends only on this contract.

---

**Version:** v0.1 (de-facto, formalized from `AGENT_NETWORK_REFERENCE.md` §1.3 / §2.2)
**Last updated:** 2026-07-05
**Realizes:** reference §1.3, §1.7, §2.2, §4.6; edge gaps §1.4 (R3/R4/R10 wiring).
