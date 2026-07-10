"""ClickUp ticket skill — entry point for the kidecon-agent sandbox.

This handler is invoked by the agent sandbox when the user wants to create
an internal ClickUp ticket (bug report or feature request). The agent has
already guided the user through the conversational triage (see the skill
definition on the hub for the full procedure). This handler performs the
mechanical steps:

  1. Read the ClickUp API key from keyring (never sent to the hub).
  2. Fetch routing config from the hub (tickets.meta).
  3. Verify expected behavior via the hub (kideconomy.verify_behavior).
  4. POST the ticket directly to ClickUp.
  5. Notify the hub's #tech Discord channel (tickets.notify).
  6. Return the ticket URL.

The handler receives a ``config`` dict (from skill.yaml / kidecon.yaml) and
an ``args`` list (positional arguments from the agent's invocation).
"""

import json
import logging

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "kidecon-agent"
CLICKUP_KEY_NAME = "api_key_clickup"


def run(args: list[str], config: dict) -> dict:
    """Skill entry point. Return a JSON-serializable result dict.

    Expected ``config`` keys:
        - hub_call_fn: callable that wraps hub MCP tool calls
          (signature: hub_call_fn(tool_name, params) -> dict)

    Routing config (list_map, default_list_id, clickup_team_id, default_assignees,
    custom_field_map) is auto-fetched from the hub via ``tickets.meta`` when not
    present in the local config. This means the hub is the single source of truth
    for ClickUp routing — the agent never hardcodes list IDs.

    Optional local overrides (in kidecon.yaml under skills.clickup_ticket.config):
        - list_map: dict mapping category -> ClickUp list ID
        - default_list_id: str fallback list ID
        - default_assignees: list[int] of ClickUp user IDs
        - custom_field_map: dict mapping field name -> custom field UUID
        - clickup_team_id: str for URL construction

    The ``args`` list carries the ticket payload as a single JSON string:
        ["{ \\"type\\": \\"bug\\", \\"title\\": \\"...\\", ... }"]
    """
    if not args:
        return {"ok": False, "error": "No ticket payload provided"}

    try:
        payload = json.loads(args[0])
    except (json.JSONDecodeError, IndexError) as exc:
        return {"ok": False, "error": f"Invalid ticket payload JSON: {exc}"}

    ticket_type = payload.get("type", "bug").lower()
    if ticket_type not in ("bug", "feature"):
        ticket_type = "bug"

    title = payload.get("title", "Untitled ticket")
    category = payload.get("category", "uncategorized")
    description = payload.get("description", "")

    # --- Step 1: Read ClickUp key from keyring ---
    api_token = _read_clickup_key()
    if not api_token:
        return {
            "ok": False,
            "error": "No ClickUp API key in keyring. Run: kidecon key add --name clickup --value <token>",
        }

    # --- Step 2: Resolve routing (fetch from hub if not in local config) ---
    from skills.clickup_ticket.clickup_client import ClickUpClient
    from skills.clickup_ticket.clickup_client import build_task_url
    from skills.clickup_ticket.clickup_client import format_description

    hub_call_fn = config.get("hub_call_fn")

    if not config.get("list_map") and hub_call_fn:
        try:
            meta = hub_call_fn("tickets.meta", {})
            if meta and isinstance(meta, dict):
                config.setdefault("list_map", meta.get("list_map", {}))
                config.setdefault("default_list_id", meta.get("default_list_id", ""))
                config.setdefault("default_assignees", meta.get("default_assignees", []))
                config.setdefault("custom_field_map", meta.get("custom_field_map", {}))
                config.setdefault("clickup_team_id", meta.get("team_id", ""))
                logger.info("Fetched ClickUp routing config from hub: %s categories", len(config.get("list_map", {})))
        except Exception:
            logger.exception("Failed to fetch routing config from hub — using local config only")

    list_id = _resolve_list_id(category, config)
    if not list_id:
        return {"ok": False, "error": f"No ClickUp list configured for category '{category}'"}

    # --- Step 3: Verify expected behavior (hub) ---
    feature = payload.get("feature")
    if hub_call_fn and feature:
        try:
            verify_result = hub_call_fn("kideconomy.verify_behavior", {"feature": feature})
            logger.info("Behavior verification: %s", verify_result)
        except Exception:
            logger.exception("Behavior verification failed — continuing anyway")

    # --- Step 4: Build and POST ticket to ClickUp ---
    formatted_desc = format_description(
        description,
        reproduction_steps=payload.get("reproduction_steps", ""),
        expected=payload.get("expected", ""),
        actual=payload.get("actual", ""),
        environment=payload.get("environment", ""),
    )

    priority = payload.get("priority", "urgent")
    client = ClickUpClient(api_token)
    try:
        task = client.create_task(
            list_id=list_id,
            name=title,
            description=formatted_desc,
            tags=[ticket_type, category, "staff"],
            priority=priority,
            assignees=config.get("default_assignees") or None,
            custom_fields=_build_custom_fields(payload, config),
            due_date=payload.get("due_date"),
        )
    except Exception as exc:
        return {"ok": False, "error": f"ClickUp API call failed: {exc}"}

    task_id = task.get("id", "unknown")
    task_url = task.get("url") or build_task_url(config.get("clickup_team_id", ""), task_id)

    # --- Step 5: Notify hub's #tech Discord channel ---
    notify_result = None
    if hub_call_fn:
        try:
            notify_result = hub_call_fn("tickets.notify", {
                "ticket_id": task_id,
                "ticket_url": task_url,
                "type": ticket_type,
                "title": title,
                "category": category,
                "priority": priority,
                "filed_by": payload.get("filed_by"),
            })
            logger.info("Discord notification sent: %s", notify_result)
        except Exception:
            logger.exception("Discord notification failed — ticket still created")

    # --- Step 6: Return result ---
    return {
        "ok": True,
        "ticket_id": task_id,
        "url": task_url,
        "type": ticket_type,
        "category": category,
        "verify_result": verify_result,
        "notified": bool(notify_result and notify_result.get("notified")),
    }


# ------------------------------------------------------------------ helpers --


def _read_clickup_key() -> str | None:
    """Read the ClickUp API token from the OS keyring."""
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, CLICKUP_KEY_NAME)
    except Exception:
        logger.exception("Failed to read ClickUp key from keyring")
        return None


def _resolve_list_id(category: str, config: dict) -> str:
    """Resolve the ClickUp list ID for a given category."""
    list_map = config.get("list_map") or {}
    if isinstance(list_map, str):
        try:
            list_map = json.loads(list_map)
        except (ValueError, TypeError):
            list_map = {}
    return list_map.get(category, config.get("default_list_id", ""))


def _build_custom_fields(payload: dict, config: dict) -> list[dict] | None:
    """Build ClickUp custom fields from agent-supplied values + config map.

    Config stores ``field_map: {label: clickup_uuid}`` (e.g. ``{"severity": "uuid-abc"}``).
    Agent sends ``payload.custom_fields: {label: value}`` (e.g. ``{"severity": "high"}``).
    The map resolves the label to the ClickUp UUID; agent values pass through.
    """
    field_map = config.get("custom_field_map") or {}
    if isinstance(field_map, str):
        try:
            field_map = json.loads(field_map)
        except (ValueError, TypeError):
            field_map = {}
    agent_fields = payload.get("custom_fields") or {}
    if not isinstance(agent_fields, dict):
        agent_fields = {}
    if not agent_fields:
        return None
    result = []
    for label, value in agent_fields.items():
        field_id = field_map.get(label, label)
        result.append({"id": field_id, "value": value})
    return result if result else None
