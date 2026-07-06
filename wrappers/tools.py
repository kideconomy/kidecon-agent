import logging
from datetime import UTC
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_BASE_DIR = Path.home() / "kidecon" / "workspace"
MESSAGES_LOG = Path.home() / "kidecon" / "messages.log"


def _resolve_path(file_path: str) -> Path:
    target = (ALLOWED_BASE_DIR / file_path).resolve()
    if not target.is_relative_to(ALLOWED_BASE_DIR):
        raise PermissionError(f"Access denied: {file_path} outside workspace")
    return target


def file_read(file_path: str) -> str:
    return _resolve_path(file_path).read_text()


def file_append_markdown(file_path: str, content: str) -> bool:
    target = _resolve_path(file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.write(content + "\n")
    return True


def message_user(message: str) -> bool:
    MESSAGES_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    with MESSAGES_LOG.open("a") as f:
        f.write(f"[{timestamp}] {message}\n")
    logger.info("Message to user: %s", message)
    return True
