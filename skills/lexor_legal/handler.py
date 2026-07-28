"""lexor-legal skill entry point.

The primary invocation path is the cognition loop's ``lexor_call`` step
action, which dispatches to ``wrappers.lexor_client.LexorClient`` directly.
This handler exists for parity with the skill package format and to support
ad-hoc CLI invocation of a single read-only tool.
"""

import json
import logging

logger = logging.getLogger(__name__)


def run(args: list[str], config: dict) -> dict:
    """Run a single Lexor read-only tool call.

    Args:
        args: ``[tool_id]`` and optionally ``[tool_id, json_params]``.
        config: must contain a ``client_fn(tool_id, params, agent_hub_tier)``
            callable, or ``hub_call_fn`` will be ignored. In practice the
            runtime passes a bound ``LexorClient.call`` as ``client_fn``.

    Returns:
        The LexorClient result dict (``{"result": ..., "error": ...}``).
    """
    if not args:
        return {"result": None, "error": "lexor-legal: no tool_id provided"}
    tool_id = args[0]
    params = {}
    if len(args) > 1:
        try:
            params = json.loads(args[1]) if isinstance(args[1], str) else dict(args[1])
        except (json.JSONDecodeError, TypeError) as exc:
            return {"result": None, "error": f"lexor-legal: invalid params: {exc}"}

    client_fn = config.get("client_fn")
    if not callable(client_fn):
        return {
            "result": None,
            "error": "lexor-legal: no client_fn configured (use the cognition loop instead)",
        }

    agent_hub_tier = int(config.get("agent_hub_tier", 1))
    return client_fn(tool_id, params, agent_hub_tier)
