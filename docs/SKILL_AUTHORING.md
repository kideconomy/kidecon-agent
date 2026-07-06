# Skill Authoring & Lifecycle

Complete guide for adding a skill to the Kidecon hub — from zero to live.

---

## Quick walkthrough (5 minutes)

```bash
# 1. Initialize the agent for local development
kidecon init --hub http://localhost:8000

# 2. Register with the hub
kidecon setup --name my-dev-agent

# 3. Generate a starter template (writes to gitignored tmp/)
kidecon skills template -o tmp/my-skill.json

# 4. Edit tmp/my-skill.json with your skill definition (see format below)

# 5. Submit for review
kidecon skills submit --file tmp/my-skill.json

# 6. Inspect the evaluation results
kidecon skills inspect <skill-id>

# 7. Check submission status
kidecon skills mine

# 8. Staff reviews and approves the skill
kidecon admin skills approve --id <skill-id>

# 9. Verify it's discoverable
kidecon skills discover
```

## Skill JSON format

Skills use the **JSON Schema convention** aligned with MCP and OpenAI function calling.

### Required fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Unique identifier on the hub. Use kebab-case. |
| `version` | string | Semantic version (e.g. `1.0.0`). |
| `category` | string | One of 7 domain namespaces (see categories below). |
| `description` | string | Functional description in third person, present tense. |

### Optional fields

| Field | Type | Description |
|---|---|---|
| `definition` | object | JSON Schema for `inputs` and `outputs`. |

### Example

```json
{
  "name": "schedule-reminder",
  "version": "1.0.0",
  "category": "scheduling",
  "description": "Retrieves upcoming calendar appointments for a given agent and sends reminder notifications via Discord.",
  "definition": {
    "inputs": {
      "type": "object",
      "properties": {
        "agent_id": {"type": "string", "description": "UUID of the agent to check appointments for"},
        "window_hours": {"type": "integer", "description": "Hours ahead to scan. Default 24."}
      },
      "required": ["agent_id"],
      "additionalProperties": false
    },
    "outputs": {
      "type": "object",
      "properties": {
        "appointments_found": {"type": "integer", "description": "Number of upcoming appointments"},
        "reminders_sent": {"type": "integer", "description": "Number of Discord reminders dispatched"}
      }
    }
  }
}
```

## Category namespaces

Pick the one namespace that best matches your skill's primary function:

| Namespace | Use for skills that... |
|---|---|
| `scheduling` | Manage appointments, calendars, availability, reminders, bookings |
| `monitoring` | Track errors, crashes, incidents, system health, logs |
| `analytics` | Analyze business data, campaigns, metrics, KPIs, reports |
| `compliance` | Check legal compliance, content moderation, policy enforcement |
| `documentation` | Search docs, retrieve knowledge base articles, references |
| `support` | Submit tickets, track issues, help desk operations |
| `communication` | Send messages, notifications, alerts, Discord DMs |

List them any time with: `kidecon skills categories`

## How evaluation works

When you submit a skill, the hub runs a normalization pipeline on your `description`:

### 1. LLM canonicalization (if configured)
The description is rewritten to a single, formal sentence capturing functional intent. Marketing language, filler words, and emoji are discarded.

### 2. Keyword matching
The canonicalized description is matched against a taxonomy of 7 task domains and 5 action types using a three-tier algorithm:

| Tier | Algorithm | Confidence |
|---|---|---|
| Exact | Text == keyword | 1.0 |
| Fuzzy | Levenshtein distance ≤ 2 | 0.8–0.95 |
| Substring | Substring match | 0.5 |

### 3. Classification
The hub assigns the skill to a domain (e.g. SCHEDULING) and an action type (e.g. NOTIFY). You can inspect these results at any time:

```bash
kidecon skills inspect <skill-id>
```

## The intern test

If a human intern couldn't invoke this skill correctly from the `description` alone, rewrite it.

| Good | Bad |
|---|---|
| "Retrieves current calendar availability for a given agent. Returns upcoming time slots within a configurable window." | "Remind me of my stuff" |
| "Queries Sentry for unresolved errors in a given project. Returns error type, count, and last-seen timestamp." | "Check for bugs" |
| "Analyses campaign performance data for a given campaign ID. Returns impressions, clicks, and conversions." | "Campaign thing" |

**Rules:**
- Write in third person, present tense
- Use specific domain keywords from the category's keyword set
- Describe the functional outcome, not the user's emotional state
- Name inputs and outputs concretely
- Avoid: marketing language, emoji, "my", "I", "please"

## Lifecycle states

```
submitted → pending → live
                    → rejected (terminal)
```

| State | Meaning |
|---|---|
| `submitted` | Initial state after POST. Evaluation pending. |
| `pending` | Passed evaluation, awaiting staff review. |
| `live` | Staff approved. Appears in `kidecon skills discover`. |
| `rejected` | Staff rejected. Terminal — submit a new skill (no revisions). |

Track your skill's state with `kidecon skills mine`.

## Rejection handling

If a skill is rejected:
- The rejection reason appears in `kidecon skills inspect <id>`
- You **cannot revise** a rejected skill — this is a security boundary
- Submit a **new skill** with a different name and version
- Learn from the rejection reason before resubmitting

## Submission modes

Three ways to submit:

```bash
# From a JSON file (recommended)
kidecon skills submit --file tmp/my-skill.json

# Inline JSON (useful from scripts/IDEs)
kidecon skills submit --inline '{"name":"my-skill","category":"scheduling","description":"..."}'

# Interactive flags
kidecon skills submit --name my-skill --category scheduling --description "..."
```

## Full command reference

```
kidecon init                            # Setup agent config for a hub environment
kidecon setup --name <name>             # Register agent, store JWT in keyring
kidecon status                          # Agent ID, tier, registration status

kidecon skills categories               # List valid skill category namespaces
kidecon skills template                 # Generate starter skill JSON (writes to tmp/)
kidecon skills guide                    # Print the full skill authoring guide
kidecon skills submit --file <path>     # Submit a skill from JSON file
kidecon skills mine                     # List your submitted skills with evaluation
kidecon skills inspect <id>             # Show full evaluation detail for a skill
kidecon skills discover                 # Search hub for approved (live) skills

kidecon admin skills pending            # Staff: list skills awaiting review
kidecon admin skills approve --id <id>  # Staff: approve a pending skill
kidecon admin skills reject --id <id> --reason "..."

kidecon doctor                          # Diagnose agent health
```

## Client integration

Any agent can discover and invoke approved skills through the hub's MCP gateway:

```python
# Discover
client.discover_skills("scheduling")  # → [{name, version, category, description}]

# Invoke
client.hub_call("scheduling.availability", {"agent_id": "..."})
```

Skills appear in discovery immediately after staff approval. No agent restart required.
