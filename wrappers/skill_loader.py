import logging

from wrappers.installed_skills import get_installed_skills
from wrappers.installed_skills import installed_lower_set

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

    def __init__(self, client, installed: list[str] | None = None):
        self.client = client
        self._index: list[dict] = []
        # Full tier-accessible catalog (informational). Hermes reads this to
        # tell the user what is installable; it is NOT the matching surface.
        self._available: list[dict] = []
        self._cache: dict[str, dict] = {}
        self._agent_tier: int | None = None
        # An explicit list pins the install set (tests / explicit callers);
        # None means re-read ``installed_skills`` from disk on every refresh so
        # a ``kidecon skills install/uninstall`` in a separate process takes
        # effect on the next refresh cycle without a restart.
        self._installed_override = list(installed) if installed is not None else None
        self._installed_lower: set[str] = self._resolve_installed()

    def _resolve_installed(self) -> set[str]:
        """Return the current lowercase installed-name set.

        Uses the constructor override when given; otherwise re-reads
        ``installed_skills`` from ``kidecon.yaml`` via the installed-skills
        module (the single writer/reader).
        """
        if self._installed_override is not None:
            return {x.lower() for x in self._installed_override if x}
        return installed_lower_set(get_installed_skills())

    def _is_installed(self, skill: dict) -> bool:
        """A skill is active only when the user explicitly installed it.

        The installed set stores skill names (see ``wrappers/installed_skills``);
        we also accept an id so a by-id install round-trips. An empty install set
        means nothing is active.
        """
        if not self._installed_lower:
            return False
        name = (skill.get("name") or "").lower()
        if name and name in self._installed_lower:
            return True
        skill_id = skill.get("id")
        return bool(skill_id) and str(skill_id).lower() in self._installed_lower

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
        """Fetch live skills from hub and keep only the locally-installed subset.

        The hub filters by tier and block state; we re-filter client-side as
        belt-and-suspenders so a skill the agent's tier cannot access is never
        retained. On top of that, the active index is restricted to the user's
        explicitly-installed skills (``installed_skills`` in ``kidecon.yaml``).
        A skill that is in-tier but not installed is never loaded into the
        matching index, so it cannot surface to instructions, tools, or config.

        The full tier-accessible catalog is kept on ``_available`` as a
        read-only view so Hermes can tell the user what is installable — it is
        deliberately NOT the matching surface.

        The install set and cached tier are re-resolved each refresh so a
        mid-session promotion/demotion or a ``kidecon skills install/uninstall``
        in another process takes effect on the next cycle rather than against a
        stale snapshot.
        """
        self._agent_tier = None
        self._installed_lower = self._resolve_installed()
        raw = self.client.discover_skills("")
        self._available = [s for s in raw if self._accessible(s)]
        dropped = len(raw) - len(self._available)
        if dropped:
            logger.warning("Dropped %d skill(s) blocked by client-side tier/block filter", dropped)
        self._index = [s for s in self._available if self._is_installed(s)]
        not_installed = len(self._available) - len(self._index)
        if not_installed and self._installed_lower:
            logger.info(
                "Filtered %d non-installed skill(s); active index is %d installed ∩ accessible",
                not_installed,
                len(self._index),
            )
        if not self._installed_lower:
            logger.info("No skills installed — run `kidecon skills install <name>` to opt in")
        logger.info("Loaded %d skills from hub", len(self._index))

    def get_index_summary(self) -> str:
        """Return a compact text summary of active (installed) skills for the system prompt."""
        if not self._index:
            return ""
        lines = ["## Available Skills", ""]
        for s in self._index:
            lines.append(f"- **{s['name']}** ({s['category']}): {s['description']}")
        return "\n".join(lines)

    def get_available_summary(self) -> str:
        """Return a read-only view of the tier-accessible catalog, installable vs active.

        Lets Hermes tell the user what skills exist but are *not* yet installed,
        alongside what is already active. This is purely informational: these
        entries are NOT part of the matching surface (``_index``), so a
        non-installed skill can still never be matched or fetched. Returns "" when
        every accessible skill is already installed (or nothing is accessible).
        """
        installable = [s for s in self._available if not self._is_installed(s)]
        if not installable:
            return ""
        lines = ["## Skills You Can Install", ""]
        lines.append("(Not active. To activate one, ask the user to run `kidecon skills install <name>`.)")
        lines += [f"- **{s['name']}** ({s['category']}): {s['description']}" for s in installable]
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

    def _is_id_possibly_installed(self, skill_id: str) -> bool:
        """Reject a non-installed skill id *before* any get_skill call.

        When the catalog snapshot knows the id, we can decide locally: a skill
        the user has not installed is refused here so it is never fetched from
        the hub. An id that is not in the current snapshot is unknown, so we
        fall through and re-gate after the (rare) fetch.
        """
        for skill in self._available:
            if skill.get("id") == skill_id:
                return self._is_installed(skill)
        return True

    def _is_servable(self, skill: dict) -> bool:
        """A fetched skill is servable only when accessible AND installed.

        Both the tier/block defense-in-depth and the user opt-in must hold.
        The reason is logged so a dropped skill is never a silent success.
        """
        skill_id = skill.get("id", "")
        if not self._accessible(skill):
            logger.warning(
                "Dropped skill %s — blocked by client-side tier/block filter",
                skill_id,
            )
            return False
        if not self._is_installed(skill):
            logger.info("Skill %s is not installed — not served", skill_id)
            return False
        return True

    def _get_cached(self, skill_id: str) -> dict | None:
        """Fetch + cache the full skill payload, or None if inaccessible.

        In addition to the tier/block gate, a skill is only served when the
        user has installed it — a non-installed (even if in-tier) skill is
        rejected *before* the hub is contacted (when the catalog snapshot knows
        it) and never resolves here, so its instructions/tools/config can never
        leak out.
        """
        if not self._is_id_possibly_installed(skill_id):
            logger.info("Skill %s is not installed — not served", skill_id)
            return None
        if skill_id not in self._cache:
            definition = self.client.get_skill(skill_id)
            if definition is None or not self._is_servable(definition):
                return None
            self._cache[skill_id] = definition
        elif not self._is_servable(self._cache[skill_id]):
            del self._cache[skill_id]
            return None
        return self._cache[skill_id]

    def find_skill(self, text: str) -> dict | None:
        """Match user message to a skill.

        Two-phase strategy:
        1. Hub-side vector search (semantic) — returns scored results.
           Only returns a match if score >= 0.4 threshold.
        2. Local keyword fallback — matches on skill name in text.

        Returns the matched skill dict or None. Only *installed* skills can ever
        match; a non-installed (but in-tier) skill is invisible here. When
        nothing is installed, this short-circuits to None (no hub call).
        """
        if not self._installed_lower:
            return None
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
                if not self._is_installed(best):
                    logger.info("Vector match '%s' is not installed — not surfaced", best["name"])
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
