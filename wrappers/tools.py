import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_BASE_DIR = Path.home() / "kidecon" / "workspace"


def file_read(file_path: str) -> str:
    target = (ALLOWED_BASE_DIR / file_path).resolve()
    if not str(target).startswith(str(ALLOWED_BASE_DIR)):
        raise PermissionError(f"Access denied: {file_path} outside workspace")
    return target.read_text()


def file_append_markdown(file_path: str, content: str) -> bool:
    target = (ALLOWED_BASE_DIR / file_path).resolve()
    if not str(target).startswith(str(ALLOWED_BASE_DIR)):
        raise PermissionError(f"Access denied: {file_path} outside workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.write(content + "\n")
    return True


def message_user(message: str) -> bool:
    # Stub — integration with Discord/Hermes messaging TBD
    logger.info("Message to user: %s", message)
    print(message)
    return True
