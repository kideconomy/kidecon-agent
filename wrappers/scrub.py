import logging
import re

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

PHONE_RE = re.compile(
    r"(?<![\w])"
    r"(?:\+?\d{1,3}[\s.\-]?)?"
    r"(?:\(?\d{2,4}\)?[\s.\-]?){2,4}\d{2,4}"
    r"(?![\w])",
)

US_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
)

LONG_ID_RE = re.compile(r"\b[A-Z0-9]{16,}\b")

REDACT_TOKEN = "[REDACTED]"


def scrub_text(text: str) -> str:
    """Deterministic regex PII scrub for free text (the real PII line).

    Redacts email, phone, SSN, UUID, and obvious long IDs. Name redaction in
    free text cannot be guaranteed by regex -- the REFLECT prompt instructs the
    model to use placeholder names ("User X"); this is the value-pattern
    backstop for leaked emails/phones/IDs the hub's key-name-only
    ``filter_message_payload`` cannot catch.
    """
    if not text or not isinstance(text, str):
        return text
    text = EMAIL_RE.sub(REDACT_TOKEN, text)
    text = PHONE_RE.sub(REDACT_TOKEN, text)
    text = US_SSN_RE.sub(REDACT_TOKEN, text)
    text = UUID_RE.sub(REDACT_TOKEN, text)
    return LONG_ID_RE.sub(REDACT_TOKEN, text)


def scrub(obj):
    """Recursively scrub all string values in a dict/list payload.

    Returns a new structure; keys are preserved (the hub filter handles keys).
    """
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, dict):
        return {key: scrub(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [scrub(item) for item in obj]
    return obj
