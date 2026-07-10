"""Glue between the clickup_ticket skill handler and the HubClient.

Provides the ``hub_call_fn`` callable that the handler expects in its config
dict, backed by the real ``HubClient.hub_call`` method. This is the only
piece that connects the standalone skill module to the live agent runtime.
"""

import logging

logger = logging.getLogger(__name__)


def make_hub_call_fn(hub_client):
    """Return a callable matching ``hub_call_fn(tool_name, params) -> dict``.

    Wraps ``HubClient.hub_call`` so the handler can call hub MCP tools
    (tickets.meta, tickets.notify, kideconomy.verify_behavior) without
    knowing about HubClient internals.
    """

    def hub_call_fn(tool_name: str, params: dict) -> dict:
        return hub_client.hub_call(tool_name, params)

    return hub_call_fn


def run_clickup_ticket(hub_client, ticket_payload: dict, local_config: dict | None = None) -> dict:
    """Run the clickup_ticket skill end-to-end.

    Args:
        hub_client: an authenticated HubClient instance.
        ticket_payload: the ticket fields (type, title, category, description, etc.)
        local_config: optional skill config overrides (list_map, etc.)

    Returns:
        The handler's result dict (ok, ticket_id, url, notified, ...).
    """
    import json

    from skills.clickup_ticket.handler import run

    config = {
        "hub_call_fn": make_hub_call_fn(hub_client),
        **(local_config or {}),
    }
    args = [json.dumps(ticket_payload)]
    return run(args, config)
