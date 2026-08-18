import logging

logger = logging.getLogger(__name__)


def merge_skill_config(defaults: dict, overrides: dict) -> dict:
    """Deep-merge per-skill config defaults with local overrides.

    Local explicit values (``kidecon.yaml``) win over skill defaults. Nested
    dicts are merged recursively; non-dict values (and keys present only in
    ``overrides``) replace outright. Returns a new dict — neither input is
    mutated.
    """
    merged = dict(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_skill_config(merged[key], value)
        else:
            merged[key] = value
    return merged


class SkillLoader:
    """Fetches skills from hub, caches them, and matches user messages to skills."""

    def __init__(self, client):
        self.client = client
        self._index: list[dict] = []
        self._cache: dict[str, dict] = {}
        self._agent_tier: int | None = None

    def _resolve_tier(self) -> int:
        """Best-effort resolve the agent's hub tier for defense-in-depth filtering.

        The hub already filters discovery/fetch by tier and block state, so
        this client-side check is belt-and-suspenders: it guards against a
        hub bug or a stale cache returning a skill the agent's tier cannot
        access. A failed tier lookup defaults to tier 0 (public-only) so we
        never silently retain a restricted skill when we can't confirm
        access.
        """
        if self._agent_tier is not None:
            return self._agent_tier
        tier = 0
        try:
            raw = self.client.get_tier()
            tier = raw if isinstance(raw, int) else int(raw)
        except Exception:  # noqa: BLE001 - tier lookup is best-effort; fall back to tier 0
            logger.debug("Could not resolve agent tier — defaulting to tier 0 for skill filtering")
            tier = 0
        self._agent_tier = tier
        return tier

    def _accessible(self, skill: dict) -> bool:
        """Defense-in-depth: drop out-of-tier or blocked skills the hub may return."""
        if skill.get("blocked"):
            return False
        min_tier = skill.get("min_hub_tier", 0)
        try:
            if int(min_tier) > self._resolve_tier():
                return False
        except (TypeError, ValueError):
            return False
        return True

    def refresh(self) -> None:
        """Fetch all live skills from hub. Called on boot and periodically.

        The hub filters by tier and block state; we re-filter client-side as
        belt-and-suspenders so a skill the agent's tier cannot access is never
        retained in the index. The cached tier is invalidated each refresh so
        a mid-session promotion/demotion is picked up rather than filtering
        against a stale tier.
        """
        self._agent_tier = None
        raw = self.client.discover_skills("")
        before = len(raw)
        self._index = [s for s in raw if self._accessible(s)]
        dropped = before - len(self._index)
        if dropped:
            logger.warning("Dropped %d skill(s) blocked by client-side tier/block filter", dropped)
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
        """Fetch full skill definition (lazy). Returns the instructions field or None.

        Defense-in-depth: if the hub returns a skill whose tier/block state is
        inaccessible to this agent, the instructions are dropped and not cached.
        A cached entry is also re-checked on every read so a mid-session demotion
        (tier 3 -> 1) cannot serve previously-fetched staff instructions from the
        cache after the agent's tier has dropped.
        """
        cached = self._get_cached(skill_id)
        return cached.get("instructions") if cached else None

    def get_skill_tools(self, skill_id: str) -> list[str] | None:
        """Return the skill's declared tools (``definition.tools``) or None.

        None means "no tools declared", so the runtime applies no per-skill tool
        gate. A list (possibly empty) means the skill declares an explicit tool
        surface that the runtime must enforce.
        """
        cached = self._get_cached(skill_id)
        if cached is None:
            return None
        return cached.get("tools")

    def get_skill_config(self, skill_id: str) -> dict | None:
        """Return the skill's delivered ``config`` defaults, or None.

        The config travels with the skill payload from discovery/get_skill. It
        is retained verbatim (already scrubbed for this agent's tier by the
        hub) — no merge is applied here. Use :meth:`resolve_skill_config` for
        the merged (local-overrides-win) view.
        """
        cached = self._get_cached(skill_id)
        if cached is None:
            return None
        return cached.get("config")

    def resolve_skill_config(self, skill_id: str, local_config: dict | None = None) -> dict | None:
        """Return the skill's config merged with local ``kidecon.yaml`` overrides.

        Local overrides live under ``skills.<skill_name>.config`` (see the
        clickup-ticket handler). Explicit local values win over skill defaults.
        Returns None when the skill is inaccessible or carries no config and no
        local override exists — preserving the current "no config = no merge"
        behavior.
        """
        cached = self._get_cached(skill_id)
        if cached is None:
            return None
        defaults = cached.get("config")
        overrides = self._local_overrides(cached.get("name", ""), local_config)
        if not isinstance(defaults, dict):
            return overrides or None
        if not overrides:
            return defaults
        return merge_skill_config(defaults, overrides)

    @staticmethod
    def _local_overrides(skill_name: str, local_config: dict | None) -> dict:
        if not local_config or not skill_name:
            return {}
        skill_entry = (local_config.get("skills") or {}).get(skill_name) or {}
        override_config = skill_entry.get("config")
        return override_config if isinstance(override_config, dict) else {}

    def find_skill_by_name(self, name: str) -> dict | None:
        """Return the index entry for a skill by (case-insensitive) name, or None."""
        target = (name or "").lower()
        for skill in self._index:
            if (skill.get("name") or "").lower() == target:
                return skill
        return None

    def _get_cached(self, skill_id: str) -> dict | None:
        """Fetch + cache the full skill payload, or None if inaccessible."""
        if skill_id not in self._cache:
            definition = self.client.get_skill(skill_id)
            if definition is None:
                return None
            if not self._accessible(definition):
                logger.warning(
                    "Dropped skill %s — blocked by client-side tier/block filter",
                    skill_id,
                )
                return None
            self._cache[skill_id] = definition
        elif not self._accessible(self._cache[skill_id]):
            logger.warning(
                "Evicted cached skill %s — agent tier no longer permits access",
                skill_id,
            )
            del self._cache[skill_id]
            return None
        return self._cache[skill_id]

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
                if not self._accessible(best):
                    return None
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
