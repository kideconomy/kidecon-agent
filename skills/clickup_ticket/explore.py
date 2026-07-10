"""Interactive ClickUp explorer — run from the kidecon-agent repo.

Usage:
    .venv/bin/python skills/clickup_ticket/explore.py

This script reads your ClickUp API key from the OS keyring (same key
that `kidecon key add --name clickup` stores) and lets you:
  - View your teams, spaces, folders, lists
  - See tasks in a list
  - Delete a task
  - Delete a list
  - Move a list to a different folder

All operations print before/after so you can see what happened.
"""

import json
import sys

import httpx

KEYRING_SERVICE = "kidecon-agent"
CLICKUP_KEY_NAME = "api_key_clickup"
CLICKUP_API = "https://api.clickup.com/api/v2"


def main():
    import keyring

    token = keyring.get_password(KEYRING_SERVICE, CLICKUP_KEY_NAME)
    if not token:
        print("No ClickUp key in keyring. Run: kidecon key add --name clickup --value <token>")
        sys.exit(1)

    headers = {"Authorization": token, "Content-Type": "application/json"}

    print("=" * 60)
    print("ClickUp Explorer")
    print("=" * 60)

    # --- Show user ---
    resp = httpx.get(f"{CLICKUP_API}/user", headers=headers, timeout=10)
    user = resp.json().get("user", {})
    print(f"\nAuthenticated as: {user.get('username', '?')} (id: {user.get('id', '?')})")

    # --- Show teams ---
    resp = httpx.get(f"{CLICKUP_API}/team", headers=headers, timeout=10)
    teams = resp.json().get("teams", [])
    print(f"\nTeams ({len(teams)}):")
    for t in teams:
        print(f"  [{t['id']}] {t['name']}")

    if not teams:
        print("No teams found. Create a workspace in ClickUp first.")
        return

    # Pick a team
    team_id = teams[0]["id"] if len(teams) == 1 else input("\nEnter team ID: ").strip()
    if not team_id:
        team_id = teams[0]["id"]

    # --- Show spaces ---
    resp = httpx.get(f"{CLICKUP_API}/team/{team_id}/space", headers=headers, timeout=10)
    spaces = resp.json().get("spaces", [])
    print(f"\nSpaces in team {team_id} ({len(spaces)}):")
    for s in spaces:
        print(f"  [{s['id']}] {s['name']}")

    if not spaces:
        print("No spaces. Let's create one.")
        space_name = input("Space name (e.g. Engineering): ").strip()
        if space_name:
            resp = httpx.post(
                f"{CLICKUP_API}/team/{team_id}/space",
                json={"name": space_name},
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                space = resp.json()
                print(f"  Created space: [{space['id']}] {space['name']}")
                spaces = [space]
            else:
                print(f"  Failed to create space: {resp.status_code} {resp.text}")
                return

    while True:
        print("\n" + "=" * 60)
        print("Commands:")
        print("  ls <space_id>        — list folders + lists in a space")
        print("  tasks <list_id>      — show tasks in a list")
        print("  deltask <task_id>    — delete a task")
        print("  dellist <list_id>    — delete a list (moves to trash)")
        print("  quit                 — exit")
        print("=" * 60)

        cmd = input("\n> ").strip()
        if not cmd:
            continue

        parts = cmd.split()
        action = parts[0].lower()

        if action in ("quit", "q", "exit"):
            break

        elif action == "ls" and len(parts) >= 2:
            sid = parts[1]
            resp = httpx.get(f"{CLICKUP_API}/space/{sid}/folder", headers=headers, timeout=10)
            folders = resp.json().get("folders", [])
            print(f"\nFolders in space {sid} ({len(folders)}):")
            for f in folders:
                print(f"  [{f['id']}] {f['name']}")
                resp2 = httpx.get(f"{CLICKUP_API}/folder/{f['id']}/list", headers=headers, timeout=10)
                lists = resp2.json().get("lists", [])
                for li in lists:
                    print(f"    [{li['id']}] {li['name']}")

            resp = httpx.get(f"{CLICKUP_API}/space/{sid}/list", headers=headers, timeout=10)
            lists = resp.json().get("lists", [])
            if lists:
                print(f"\nLists directly in space {sid} (no folder) ({len(lists)}):")
                for li in lists:
                    print(f"  [{li['id']}] {li['name']}")

        elif action == "tasks" and len(parts) >= 2:
            lid = parts[1]
            resp = httpx.get(f"{CLICKUP_API}/list/{lid}/task", headers=headers, timeout=10)
            tasks = resp.json().get("tasks", [])
            print(f"\nTasks in list {lid} ({len(tasks)}):")
            for t in tasks:
                print(f"  [{t['id']}] {t['name']}")
                print(f"       url: https://app.clickup.com/t{team_id}/{t['id']}")

        elif action == "deltask" and len(parts) >= 2:
            tid = parts[1]
            confirm = input(f"Delete task {tid}? (y/n): ").strip().lower()
            if confirm == "y":
                resp = httpx.delete(f"{CLICKUP_API}/task/{tid}", headers=headers, timeout=10)
                print(f"  {'Deleted' if resp.status_code in (200, 204) else 'Failed'}: {resp.status_code}")

        elif action == "dellist" and len(parts) >= 2:
            lid = parts[1]
            confirm = input(f"Delete list {lid}? (y/n): ").strip().lower()
            if confirm == "y":
                resp = httpx.delete(f"{CLICKUP_API}/list/{lid}", headers=headers, timeout=10)
                print(f"  {'Deleted' if resp.status_code in (200, 204) else 'Failed'}: {resp.status_code}")

        else:
            print("Unknown command. Try: ls <space_id>, tasks <list_id>, deltask <task_id>, dellist <list_id>, quit")


if __name__ == "__main__":
    main()