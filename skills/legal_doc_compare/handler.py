"""legal-doc-compare skill entry point.

The primary invocation path is the cognition loop: the hub-distributed
instructions drive ``local_tool`` steps (``docs_sync``, ``file_read``,
``text_diff``, ``file_append_markdown``) and ``lexor_call`` steps. This
handler exists for parity with the skill package format and to support an
ad-hoc mirror sync from a CLI context.
"""

import logging

logger = logging.getLogger(__name__)


def run(args: list[str], config: dict) -> dict:
    """Run a docs-mirror sync.

    Args:
        args: unused (reserved). Pass ``["sync"]`` explicitly for clarity.
        config: must contain a ``sync_fn(agent_hub_tier)`` callable returning
            the ``DocsMirror.sync`` result dict. In practice the runtime passes
            a bound ``DocsMirror.sync`` as ``sync_fn``.

    Returns:
        The DocsMirror sync result dict (``{"ok": ..., "error": ..., ...}``).
    """
    sync_fn = config.get("sync_fn")
    if not callable(sync_fn):
        return {
            "ok": False,
            "error": "legal-doc-compare: no sync_fn configured (use the cognition loop instead)",
        }

    # agent_hub_tier is caller-supplied on this ad-hoc path and therefore not
    # trusted as the gate — the real staff-only enforcement is the keyring
    # provisioning layer inside DocsMirror.sync (no credential, no sync).
    agent_hub_tier = int(config.get("agent_hub_tier", 1))
    return sync_fn(agent_hub_tier)
