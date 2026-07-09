import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_DIR = Path.home() / "kidecon" / "memory"

SOUL_FILE = "SOUL.md"
USER_FILE = "USER.md"
CAPABILITIES_FILE = "CAPABILITIES.md"
PLAN_FILE = "PLAN.md"
MEMORY_FILE = "MEMORY.md"
INDEX_FILE = ".index.json"

DEFAULT_LIMITS: dict[str, int] = {
    SOUL_FILE: 5000,
    USER_FILE: 5000,
    CAPABILITIES_FILE: 3000,
}

DEFAULT_DESCRIPTIONS: dict[str, str] = {
    SOUL_FILE: "The agent's core persona, voice, and values. Edit when the agent's character should shift.",
    USER_FILE: "The user model: name, goals, preferences, history signals. Edit when the user's context changes.",
    CAPABILITIES_FILE: "A distilled always-on block of what the agent can do. Hand-maintained.",
}

DEFAULT_BODIES: dict[str, str] = {
    SOUL_FILE: "# Soul\nYou are Hermes, a warm but direct learning companion. You teach by asking, not lecturing.\nNever promise outcomes you can't verify.\n",
    USER_FILE: "# User\n(No user signals recorded yet.)\n",
    CAPABILITIES_FILE: "# Capabilities\n- Reason about the user's message and respond concisely.\n- Use the safety firewall on Discord traffic.\n- Read/write local memory files (MEMORY/SOUL/USER/CAPABILITIES).\n",
}

SECTION_RE = re.compile(r"^##\s+\[(?P<tag>[^\]]+)\]\s*$")
BULLET_RE = re.compile(r"^\s*-\s+")


@dataclass
class Block:
    frontmatter: dict
    body: str

    @property
    def limit(self) -> int | None:
        limit = self.frontmatter.get("limit")
        return int(limit) if limit is not None else None


class MemoryStore:
    """Direct pathlib I/O for the always-on persona/memory blocks under ``~/kidecon/memory``.

    Owns SOUL/USER/CAPABILITIES (frontmatter + char-limited bodies), the
    append-only MEMORY.md (tagged sections), the cheap ``.index.json`` recall
    index, and the mutable PLAN.md scratch file. Lives **outside**
    ``tools.py`` workspace containment on purpose (memory I/O is not a tool).
    """

    def __init__(self, memory_dir: Path | None = None) -> None:
        self.dir = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.dir / "journal").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Core blocks (SOUL / USER / CAPABILITIES)
    # ------------------------------------------------------------------
    def read_block(self, name: str) -> Block:
        path = self.dir / name
        if not path.exists():
            return Block(frontmatter={}, body="")
        text = path.read_text()
        return self._parse_block(text)

    def write_block(self, name: str, body: str, *, limit: int | None = None) -> tuple[bool, str]:
        """Replace a block's body, preserving its frontmatter.

        Enforces the char limit (frontmatter ``limit`` or the ``limit`` arg).
        Over-limit bodies are **rejected** (never silently accepted) per R3.
        Enforces the char limit. Precedence: frontmatter ``limit`` (spec §4.1)
        → the ``limit`` arg → ``DEFAULT_LIMITS``. Over-limit bodies are
        **rejected** (never silently accepted) per R3. Returns ``(ok, reason)``.
        """
        fm_limit = self.read_block(name).limit
        if fm_limit is not None:
            effective_limit = fm_limit
        elif limit is not None:
            effective_limit = limit
        else:
            effective_limit = DEFAULT_LIMITS.get(name)
        if effective_limit is not None and len(body) > effective_limit:
            reason = f"{name} body {len(body)} > limit {effective_limit} — rejected"
            logger.warning("Block write rejected: %s", reason)
            return False, reason

        existing = self.read_block(name)
        frontmatter = existing.frontmatter or self._default_frontmatter(name)
        path = self.dir / name
        path.write_text(self._serialize_block(frontmatter, body))
        return True, "ok"

    def ensure_default_blocks(self, limits: dict[str, int] | None = None) -> None:
        """Seed SOUL/USER/CAPABILITIES with defaults if absent (persona bootstrap).

        ``limits`` (from ``cognition.*`` config) are written into the frontmatter
        so ``write_block`` enforces the configured bound. After seeding, the
        frontmatter ``limit`` is the source of truth (spec §4.1/§5.1).
        """
        limits = limits or DEFAULT_LIMITS
        for name in (SOUL_FILE, USER_FILE, CAPABILITIES_FILE):
            path = self.dir / name
            if not path.exists():
                fm = self._default_frontmatter(name)
                fm["limit"] = limits.get(name, DEFAULT_LIMITS.get(name, 5000))
                path.write_text(self._serialize_block(fm, DEFAULT_BODIES[name]))
                logger.info("Seeded default block %s (limit=%s)", name, fm["limit"])

    def load_core_blocks(self) -> str:
        """Concatenated bodies of SOUL/USER/CAPABILITIES for the system-prompt tail."""
        parts: list[str] = []
        for name in (SOUL_FILE, USER_FILE, CAPABILITIES_FILE):
            body = self.read_block(name).body.strip()
            if body:
                parts.append(body)
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # MEMORY.md (append-only, tagged) + .index.json
    # ------------------------------------------------------------------
    def read_memory(self) -> str:
        path = self.dir / MEMORY_FILE
        if not path.exists():
            return ""
        return path.read_text()

    def append_memory(self, tag: str, line: str, source: str = "reflection") -> list[int]:
        """Append a bullet under ``## [tag]`` in MEMORY.md and refresh the index.

        Adds the ``(YYYY-MM-DD, src: <source>)`` provenance suffix if the line
        does not already end with one. Returns the 1-indexed line range written.
        """
        path = self.dir / MEMORY_FILE
        text = path.read_text() if path.exists() else ""
        lines = text.splitlines()
        if not lines or not text.lstrip().startswith("# Memory"):
            lines = ["# Memory", ""]

        stamped = self._stamp_line(line, source)
        self._insert_bullet(lines, tag, stamped)
        path.write_text("\n".join(lines) + "\n")
        ranges = self._rebuild_index(tag)
        logger.info("Appended memory under [%s]; index=%s", tag, ranges)
        return ranges.get(tag, [0, 0])

    def read_index(self) -> dict:
        path = self.dir / INDEX_FILE
        if not path.exists():
            return {"tags_by_recency": [], "last_entry_line": 0}
        try:
            return json.loads(path.read_text()) or {}
        except (json.JSONDecodeError, ValueError):
            logger.exception("Corrupt %s — resetting", INDEX_FILE)
            return {"tags_by_recency": [], "last_entry_line": 0}

    def update_index(self) -> dict:
        return self._rebuild_index()

    def recall(self, cues: list[str], top_k: int = 5) -> str:
        """Dumb, fast recall: match cues against index tags, read those sections."""
        index = self.read_index()
        if not index:
            return ""
        lowered = [c.lower() for c in cues if c]
        matched: list[str] = []
        for tag in index.get("tags_by_recency", []):
            tag_lower = tag.lower()
            if any(cue in tag_lower or tag_lower in cue for cue in lowered):
                matched.append(tag)
            if len(matched) >= top_k:
                break
        if not matched:
            return ""
        return self._read_sections(matched)

    # ------------------------------------------------------------------
    # PLAN.md (mutable scratch)
    # ------------------------------------------------------------------
    def read_plan(self) -> str:
        path = self.dir / PLAN_FILE
        return path.read_text() if path.exists() else ""

    def write_plan(self, task: str, steps: list[dict], status: str = "in_progress") -> None:
        path = self.dir / PLAN_FILE
        body_lines = ["# Active Plan", f"task: {task!r}", "steps:"]
        for step in steps:
            mark = "[x]" if step.get("done") else "[ ]"
            body_lines.append(f"- {mark} {step.get('action', '')} {step.get('params', '')}".rstrip())
        body_lines.append(f"status: {status}")
        body_lines.append(f"created: {datetime.now(UTC).isoformat()}")
        path.write_text("\n".join(body_lines) + "\n")

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_block(text: str) -> Block:
        if not text.startswith("---"):
            return Block(frontmatter={}, body=text)
        end = text.find("\n---", 3)
        if end == -1:
            return Block(frontmatter={}, body=text)
        fm_text = text[3:end].strip()
        body = text[end + 4 :].lstrip("\n")
        try:
            frontmatter = yaml.safe_load(fm_text) or {}
        except Exception:
            logger.exception("Corrupt frontmatter — treating as empty")
            frontmatter = {}
        return Block(frontmatter=frontmatter, body=body)

    @staticmethod
    def _serialize_block(frontmatter: dict, body: str) -> str:
        fm = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
        return f"---\n{fm}\n---\n{body}"

    @staticmethod
    def _default_frontmatter(name: str) -> dict:
        return {
            "description": DEFAULT_DESCRIPTIONS.get(name, ""),
            "limit": DEFAULT_LIMITS.get(name, 5000),
        }

    @staticmethod
    def _stamp_line(line: str, source: str) -> str:
        line = line.rstrip()
        if re.search(r"\(src:\s*\w+\)\s*$", line):
            return line
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        return f"{line} ({date}, src: {source})"

    @staticmethod
    def _insert_bullet(lines: list[str], tag: str, bullet: str) -> None:
        section_header = f"## [{tag}]"
        idx = 0
        n = len(lines)
        while idx < n:
            if lines[idx].strip() == section_header:
                break
            idx += 1
        else:
            if lines and lines[-1].strip() != "":
                lines.append("")
            lines.append(section_header)
            lines.append(f"- {bullet}")
            return

        end = idx + 1
        while end < n and BULLET_RE.match(lines[end]):
            end += 1
        lines.insert(end, f"- {bullet}")

    def _rebuild_index(self, touched_tag: str | None = None) -> dict:
        path = self.dir / MEMORY_FILE
        lines = path.read_text().splitlines() if path.exists() else []
        ranges: dict[str, list[list[int]]] = {}
        current_tag: str | None = None
        start: int | None = None
        last_bullet: int | None = None
        for i, raw in enumerate(lines, start=1):
            m = SECTION_RE.match(raw)
            if m:
                if current_tag is not None and last_bullet is not None:
                    ranges.setdefault(current_tag, []).append([start, last_bullet])
                current_tag = m.group("tag")
                start = i + 1
                last_bullet = None
            elif current_tag is not None and BULLET_RE.match(raw):
                last_bullet = i
            elif current_tag is not None and raw.strip() == "" and last_bullet is not None:
                ranges.setdefault(current_tag, []).append([start, last_bullet])
                current_tag = None
                start = None
                last_bullet = None
        if current_tag is not None and last_bullet is not None:
            ranges.setdefault(current_tag, []).append([start, last_bullet])

        old = self.read_index()
        recency: list[str] = list(old.get("tags_by_recency", []))
        ordered_tags = list(ranges.keys())
        if touched_tag and touched_tag in ordered_tags:
            ordered_tags.remove(touched_tag)
            ordered_tags.insert(0, touched_tag)
        for tag in recency:
            if tag in ranges and tag not in ordered_tags:
                ordered_tags.append(tag)
        index = {
            **ranges,
            "tags_by_recency": ordered_tags,
            "last_entry_line": len(lines),
        }
        (self.dir / INDEX_FILE).write_text(json.dumps(index, indent=2) + "\n")
        return index

    def _read_sections(self, tags: list[str]) -> str:
        lines = self.read_memory().splitlines()
        if not lines:
            return ""
        out: list[str] = []
        current_tag: str | None = None
        for raw in lines:
            m = SECTION_RE.match(raw)
            if m:
                current_tag = m.group("tag")
                if current_tag in tags:
                    out.append(raw)
                continue
            if current_tag in tags and BULLET_RE.match(raw):
                out.append(raw)
        return "\n".join(out).strip()
