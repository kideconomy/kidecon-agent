import difflib
import logging
from datetime import UTC
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MESSAGES_LOG = Path.home() / "kidecon" / "messages.log"
MAX_DIFF_CHARS = 200_000

_workspace_dir: Path | None = None


def set_workspace_dir(path) -> None:
    """Set the workspace directory used by file tools and the docs mirror.

    Called at boot from the ``workspace_dir`` config key. Resolved to an
    absolute path here so callers can rely on ``workspace_dir()`` being
    containment-safe.
    """
    global _workspace_dir
    _workspace_dir = Path(path).expanduser().resolve()


def workspace_dir() -> Path:
    """The active workspace directory (default ``~/kidecon/workspace``)."""
    if _workspace_dir is not None:
        return _workspace_dir
    return Path.home() / "kidecon" / "workspace"


def _resolve_path(file_path: str) -> Path:
    base = workspace_dir().resolve()
    target = (base / file_path).resolve()
    if not target.is_relative_to(base):
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


def text_diff(path_a: str, path_b: str, context_lines: int = 3) -> str:
    """Deterministic unified diff of two workspace text files.

    Returns a friendly string in every case (never raises into a turn):
    missing/unreadable files produce an explanatory message, identical files
    produce "No differences.", and very large diffs are truncated with a note.
    """
    try:
        target_a = _resolve_path(path_a)
        target_b = _resolve_path(path_b)
    except PermissionError as exc:
        return f"Diff unavailable: {exc}"

    try:
        lines_a = target_a.read_text().splitlines(keepends=True)
    except OSError as exc:
        return f"Diff unavailable: could not read '{path_a}' ({exc.strerror or exc})."
    try:
        lines_b = target_b.read_text().splitlines(keepends=True)
    except OSError as exc:
        return f"Diff unavailable: could not read '{path_b}' ({exc.strerror or exc})."

    diff_lines = list(
        difflib.unified_diff(lines_a, lines_b, fromfile=path_a, tofile=path_b, n=context_lines),
    )
    if not diff_lines:
        return f"No differences. '{path_a}' and '{path_b}' are identical."

    diff_text = "".join(diff_lines)
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS] + (
            f"\n... [diff truncated at {MAX_DIFF_CHARS} characters — compare smaller sections for the rest]"
        )
    return diff_text
