import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SESSIONS_DIR = Path.home() / "kidecon" / "memory" / "sessions"


class SessionStore:
    """Per-session append-only JSONL message history with bounded tail loading.

    Only human (Discord) sources get persistent sessions; A2A stays stateless.
    On each turn the last ``window`` lines are loaded into context. The on-disk
    tail re-seeds working memory on the first turn after a restart (persona
    survives because long-term memory lives in files, not the process).
    """

    def __init__(self, sessions_dir: Path | None = None, window: int = 12) -> None:
        self.dir = Path(sessions_dir) if sessions_dir else DEFAULT_SESSIONS_DIR
        self.window = window
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, source: str, user_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{source}_{user_id}")
        return self.dir / f"{safe}.jsonl"

    def append(self, source: str, user_id: str, entry: dict) -> None:
        """Append one JSON line to the session's JSONL file."""
        path = self._path(source, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def tail(self, source: str, user_id: str, k: int | None = None) -> list[dict]:
        """Return the last ``k`` (default ``window``) JSON lines as dicts."""
        path = self._path(source, user_id)
        if not path.exists():
            return []
        limit = k if k is not None else self.window
        lines = path.read_text().splitlines()
        tail = lines[-limit:] if limit else lines
        out: list[dict] = []
        for raw in tail:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                out.append(json.loads(stripped))
            except json.JSONDecodeError:
                logger.warning("Skipping corrupt session line in %s", path)
        return out

    def count(self, source: str, user_id: str) -> int:
        path = self._path(source, user_id)
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text().splitlines() if line.strip())

    def compact(self, source: str, user_id: str, threshold: int, head_keep: int = 4) -> int:
        """Letta-style compaction: keep a short head + the recent tail, prune the middle.

        Returns the number of lines pruned. Full LLM summarize-into-MEMORY is a
        separate dreaming step; here we keep the head (earliest context) and the
        recent working tail and drop the middle to bound the always-loaded slice.
        """
        path = self._path(source, user_id)
        if not path.exists():
            return 0
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        if len(lines) <= threshold:
            return 0
        keep_head = lines[:head_keep]
        keep_tail = lines[-self.window :]
        pruned = len(lines) - len(keep_head) - len(keep_tail)
        path.write_text("\n".join(keep_head + keep_tail) + "\n")
        logger.info("Compacted session %s: pruned %d middle lines", path.name, pruned)
        return pruned
