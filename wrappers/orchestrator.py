"""Orchestrator delegation logic — additive overlay on the standard CognitiveEngine.

The orchestrator is a regular agent with one additional capability:
it can delegate Discord DM tasks to workers via A2A messages.

Worker roster is maintained locally — the orchestrator knows worker
addresses because it created them (profiles) and checks liveness via PID.
"""

import logging
from typing import TYPE_CHECKING

from wrappers.cognition import A2A_TASK_REQUEST
from wrappers.cognition import A2A_TASK_RESULT

if TYPE_CHECKING:
    from wrappers.hub_client import HubClient
    from wrappers.profile_store import Profile

logger = logging.getLogger(__name__)

DELEGATION_ACK_TEMPLATE = (
    "Working on it — delegated to {worker_name}. I'll get back to you shortly."
)


def load_worker_roster() -> dict[str, dict]:
    """Load local worker agents from profiles.

    Returns dict of {name: {agent_id, pid, online}} for all workers.
    Only returns workers that are registered (have JWT) and have role=worker.
    """
    from wrappers.profile_store import list_profile_objects
    from wrappers.profile_store import read_pid

    roster: dict[str, dict] = {}
    for profile in list_profile_objects():
        if profile.role != "worker":
            continue
        if not profile.jwt:
            continue

        pid = read_pid(profile)
        roster[profile.name] = {
            "agent_id": profile.agent_id,
            "profile": profile,
            "pid": pid,
            "online": pid is not None,
        }

    return roster


def select_worker(roster: dict[str, dict], task_description: str) -> dict | None:
    """Select the best worker for a task.

    Current strategy: simple round-robin over online workers.
    Future: LLM-based matching using worker names and task descriptions.
    """
    online = {name: w for name, w in roster.items() if w["online"]}
    if not online:
        return None

    for name, worker in online.items():
        if name.lower() in task_description.lower():
            return worker

    return next(iter(online.values()))


def delegate_task(
    client: "HubClient",
    worker: dict,
    task_text: str,
    task_type: str = "general",
) -> str:
    """Send an A2A task_request to a worker. Returns the task message_id."""
    result = client.send_message(
        to_agent_id=worker["agent_id"],
        msg_type=A2A_TASK_REQUEST,
        payload={
            "text": task_text,
            "source": "a2a",
            "task_type": task_type,
        },
    )
    return result.get("message_id", "")


def relay_to_discord(
    client: "HubClient",
    orchestrator_agent_id: str,
    discord_user_id: str,
    result_text: str,
) -> None:
    """Send a follow-up Discord DM with the worker's result.

    Creates a message addressed to the orchestrator with type=discord_dm
    so the hub's Discord bridge picks it up and delivers it to the user.
    """
    try:
        client.send_message(
            to_agent_id=orchestrator_agent_id,
            msg_type="discord_dm",
            payload={
                "discord_user_id": discord_user_id,
                "text": result_text,
                "source": "a2a_response",
            },
        )
    except Exception:
        logger.exception("Failed to relay worker response to Discord")