"""Shared HTTP error-detail extraction for hub responses.

The hub returns human-readable error explanations as a JSON ``{"detail": ...}``
body on 4xx/5xx. This helper pulls that string safely (non-JSON bodies,
non-dict bodies, missing key) so callers can surface a meaningful message
instead of a raw ``httpx.HTTPStatusError``.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


def hub_detail(response: httpx.Response, fallback: str) -> str:
    """Return the hub's ``detail`` string from a JSON error body.

    Falls back to ``fallback`` when the body is not JSON, not a dict, or has
    no ``detail`` field. Never raises.
    """
    try:
        body = response.json()
    except (ValueError, TypeError):
        return fallback
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail or fallback
