"""CANONICAL SOURCE: kidecon-hub/shared/llm_clients/
DO NOT EDIT in vendored copies — edit here and run sync.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TierRouter:
    """Resolve a message dict to one of the LLM tiers: ``daily``, ``strong``, or ``coding``.

    The tier determines which model string (from ``kidecon.yaml``) is used for
    the LLM call.

    Resolution rules (first match wins):

    1. ``payload.text`` starts with ``/code`` **or** ``type == "code_review"`` → ``"coding"``
    2. ``payload.text`` starts with ``/think`` → ``"strong"``
    3. Everything else → ``"daily"``
    """

    @staticmethod
    def resolve_tier(message: dict) -> str:
        """Return ``"daily"``, ``"strong"``, or ``"coding"``."""
        text: str = message.get("payload", {}).get("text", "")
        msg_type: str = message.get("type", "")

        if text.startswith("/code") or msg_type == "code_review":
            return "coding"
        if text.startswith("/think"):
            return "strong"
        return "daily"
