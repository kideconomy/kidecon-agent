import logging

logger = logging.getLogger(__name__)


class SkillLoader:
    """Fetches skills from hub, caches them, and matches user messages to skills."""

    def __init__(self, client):
        self.client = client
        self._index: list[dict] = []
        self._cache: dict[str, dict] = {}

    def refresh(self) -> None:
        """Fetch all live skills from hub. Called on boot and periodically."""
        self._index = self.client.discover_skills("")
        logger.info("Loaded %d skills from hub", len(self._index))

    def get_index_summary(self) -> str:
        """Return a compact text summary of available skills for the system prompt."""
        if not self._index:
            return ""
        lines = ["## Available Skills", ""]
        for s in self._index:
            lines.append(f"- **{s['name']}** ({s['category']}): {s['description']}")
        return "\n".join(lines)

    def get_skill_instructions(self, skill_id: str) -> str | None:
        """Fetch full skill definition (lazy). Returns the instructions field or None."""
        if skill_id not in self._cache:
            definition = self.client.get_skill(skill_id)
            if definition is None:
                return None
            self._cache[skill_id] = definition
        return self._cache[skill_id].get("instructions")

    def find_skill(self, text: str) -> dict | None:
        """Match user message to a skill.

        Two-phase strategy:
        1. Hub-side vector search (semantic) — returns scored results.
           Only returns a match if score >= 0.4 threshold.
        2. Local keyword fallback — matches on skill name in text.

        Returns the matched skill dict or None.
        """
        matched = self._vector_find(text)
        if matched is not None:
            return matched
        return self._keyword_find(text)

    def _vector_find(self, text: str, threshold: float = 0.4) -> dict | None:
        try:
            results = self.client.discover_skills(text, vector=True)
            if not results:
                return None
            best = results[0]
            score = best.get("score", 0)
            if isinstance(score, (int, float)) and score >= threshold:
                logger.info("Vector match: '%s' (score=%.3f)", best["name"], score)
                return best
        except Exception:
            logger.debug("Vector search failed — falling back to keyword")
        return None

    def _keyword_find(self, text: str) -> dict | None:
        text_lower = text.lower()
        for skill in self._index:
            name = skill.get("name", "").lower()
            if name in text_lower:
                return skill
            desc = skill.get("description", "").lower()
            name_tokens = name.replace("-", " ").split()
            desc_tokens = [t for t in desc.split() if len(t) > 3]
            all_tokens = name_tokens + desc_tokens
            matched_tokens = sum(1 for token in all_tokens if token in text_lower)
            if matched_tokens >= 2:
                return skill
        return None