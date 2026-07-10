"""End-to-end test: create a real ClickUp ticket via the full agent → hub → ClickUp flow.

Usage:
    .venv/bin/python skills/clickup_ticket/e2e_test.py

Prerequisites:
    1. Hub running (kidecon-hub) with CLICKUP_LIST_MAP, DISCORD_TECH_CHANNEL_ID configured
    2. ClickUp API key in keyring: kidecon key add --name clickup --value pk_xxx
    3. Agent registered and staff-promoted on the hub
    4. kidecon.yaml exists with hub_url

WARNING: This script posts a real ticket to ClickUp and a real Discord notification
to the live #tech channel (the conftest fixture only applies during pytest). The test
ticket is deleted on cleanup, but the Discord notification is permanent.

To skip Discord notification (safe for CI / repeated runs), set:
    KIDECON_E2E_SKIP_NOTIFY=1

To skip the whole ClickUp create step (re-verify config only), set:
    KIDECON_E2E_READONLY=1
"""

import json
import os
import sys

import httpx

KEYRING_SERVICE = "kidecon-agent"
CLICKUP_KEY_NAME = "api_key_clickup"
CLICKUP_API = "https://api.clickup.com/api/v2"

task_id_created = None


def main():
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

    import keyring
    import yaml

    config_path = pathlib.Path.home() / ".config" / "kidecon" / "kidecon.yaml"
    if not config_path.exists():
        print("kidecon.yaml not found. Run 'kidecon init' first.")
        sys.exit(1)
    config = yaml.safe_load(config_path.read_bytes())
    hub_url = config["hub_url"]

    from wrappers.hub_client import HubClient

    client = HubClient(hub_url=hub_url, kideconomy_api_url=config.get("kideconomy_api_url", ""))

    if not client.jwt:
        print("Not registered. Run 'kidecon setup' first.")
        sys.exit(1)

    print(f"Hub: {hub_url}")
    print(f"Agent ID: {client.agent_id}")
    print(f"KIDECON_E2E_READONLY={os.environ.get('KIDECON_E2E_READONLY', '0')}")
    print(f"KIDECON_E2E_SKIP_NOTIFY={os.environ.get('KIDECON_E2E_SKIP_NOTIFY', '0')}")

    readonly = os.environ.get("KIDECON_E2E_READONLY") == "1"
    skip_notify = os.environ.get("KIDECON_E2E_SKIP_NOTIFY") == "1"
    global task_id_created

    # --- Step 1: Read ClickUp key from keyring ---
    print("\n--- Step 1: Read ClickUp key from keyring ---")
    api_token = keyring.get_password(KEYRING_SERVICE, CLICKUP_KEY_NAME)
    if not api_token:
        print("No ClickUp key in keyring. Run: kidecon key add --name clickup --value <token>")
        sys.exit(1)
    print("  Key found (masked).")
    headers = {"Authorization": api_token, "Content-Type": "application/json"}

    # --- Step 2: Fetch routing config from hub (tickets.meta) ---
    print("\n--- Step 2: Call tickets.meta on hub ---")
    meta_result = client.hub_call("tickets.meta", {})
    print(f"  Result: {json.dumps(meta_result, indent=2)}")
    list_map = meta_result.get("result", {}).get("list_map", {})
    team_id = meta_result.get("result", {}).get("team_id", "")
    if not list_map:
        print("ERROR: Hub returned no list_map. Check CLICKUP_LIST_MAP in hub .env.")
        sys.exit(1)

    # --- Step 3: Verify behavior (kideconomy.verify_behavior) ---
    print("\n--- Step 3: Call kideconomy.verify_behavior on hub ---")
    verify_result = client.hub_call("kideconomy.verify_behavior", {"feature": "transfer"})
    print(f"  Result: {json.dumps(verify_result, indent=2)}")

    if readonly:
        print("\n--- READONLY: Skipping create + notify ---")
        print_summary(list_map, verify_result, team_id)
        return

    # --- Step 4: Build and POST ticket to ClickUp ---
    print("\n--- Step 4: POST ticket to ClickUp ---")
    ticket_type = "bug"
    category = "banking"
    list_id = list_map.get(category, list_map.get("bug", ""))
    if not list_id:
        print(f"ERROR: No list ID for category '{category}' in list_map")
        sys.exit(1)

    title = "E2E TEST — please delete"
    ticket_body = {
        "name": title,
        "description": (
            "**Steps to reproduce**\n1. Run e2e_test.py\n2. Verify ticket appears\n\n"
            "**Expected**\nTicket created successfully in ClickUp\n\n"
            "**Actual**\n(automated test)\n\n"
            "**Environment**\nAutomated E2E test run"
        ),
        "tags": [ticket_type, category, "staff"],
        "priority": 1,
        "notify_all": True,
        "check_required_custom_fields": False,
    }

    global task_id_created
    resp = httpx.post(
        f"{CLICKUP_API}/list/{list_id}/task",
        json=ticket_body,
        headers=headers,
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR: ClickUp API failed (HTTP {resp.status_code}): {resp.text}")
        sys.exit(1)

    task = resp.json()
    task_id_created = task.get("id", "unknown")
    task_url = (
        f"https://app.clickup.com/t{team_id}/{task_id_created}"
        if team_id
        else f"https://app.clickup.com/t/{task_id_created}"
    )
    print(f"  Created: [{task_id_created}] {title}")
    print(f"  URL: {task_url}")

    # --- Step 5: Verify ticket exists in ClickUp ---
    print("\n--- Step 5: Verify ticket exists in ClickUp ---")
    resp = httpx.get(f"{CLICKUP_API}/task/{task_id_created}", headers=headers, timeout=10)
    if resp.status_code == 200:
        fetched = resp.json()
        print(f"  Verified: [{fetched['id']}] {fetched['name']}")
    else:
        print(f"  WARNING: Could not fetch task (HTTP {resp.status_code})")

    # --- Step 6: Notify hub's #tech Discord channel ---
    if skip_notify:
        print("\n--- Step 6: Skipped (KIDECON_E2E_SKIP_NOTIFY=1) ---")
        notify_result = {"result": {"notified": False, "skipped": True}}
    else:
        print("\n--- Step 6: Call tickets.notify on hub ---")
        print("  WARNING: This posts to the live #tech Discord channel.")
        notify_result = client.hub_call("tickets.notify", {
            "ticket_id": task_id_created,
            "ticket_url": task_url,
            "type": ticket_type,
            "title": title,
            "category": category,
            "priority": "urgent",
            "filed_by": "e2e-test",
        })
    print(f"  Result: {json.dumps(notify_result, indent=2)}")

    # --- Summary ---
    print_summary(list_map, verify_result, notify_result, team_id)


def cleanup():
    """Delete the test ticket if one was created."""
    global task_id_created
    if not task_id_created:
        return

    import keyring

    api_token = keyring.get_password(KEYRING_SERVICE, CLICKUP_KEY_NAME)
    if not api_token:
        print("  Cannot clean up — no ClickUp key in keyring.")
        return

    headers = {"Authorization": api_token, "Content-Type": "application/json"}
    print(f"\n--- Cleanup: Delete test task {task_id_created} ---")
    resp = httpx.delete(f"{CLICKUP_API}/task/{task_id_created}", headers=headers, timeout=10)
    if resp.status_code in (200, 204):
        print(f"  Deleted: {task_id_created}")
    else:
        print(f"  WARNING: Could not delete task (HTTP {resp.status_code})")


def print_summary(list_map=None, verify_result=None, notify_result=None, team_id=None):
    notified_ok = bool(notify_result and notify_result.get("result", {}).get("notified"))
    print("\n" + "=" * 60)
    print("E2E TEST SUMMARY")
    print("=" * 60)
    print(f"  Hub tickets.meta:           {'PASS' if list_map else 'FAIL'}")
    print(f"  Hub verify_behavior:       {'PASS' if verify_result else 'FAIL'}")
    print(f"  ClickUp create task:        {'PASS' if task_id_created else 'N/A'}")
    print(f"  Hub tickets.notify:        {'PASS' if notified_ok else ('SKIP' if notify_result and notify_result.get('result', {}).get('skipped') else 'FAIL')}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
