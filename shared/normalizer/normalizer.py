# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                      CANONICAL SOURCE — kidecon-hub                          ║
# ║              DO NOT EDIT in vendored copies — run `make sync-lexicon`.       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
"""Edge-vendored normalizer, decomposed into two functions.

The hub ``services/normalizer.py`` exposes a single ``normalize_text`` that
always calls an LLM rewrite. The edge cannot afford that on the ``daily`` tier
(latency parity), so the vendored copy is decomposed:

- ``normalize_keyword(raw)`` -- keyword/fuzzy lexicon match. **Always** runs,
  zero LLM, instant. Resolves ``domain_id``/``action_id``/``confidence`` for
  routing/tagging/skill-selection.
- ``normalize_llm_rewrite(raw, provider, model)`` -- optional LLM canonical
  rewrite, only invoked for tiers listed in ``normalization.llm_rewrite_on``.

A ``NormalizationResult`` is metadata only -- the reasoning LLM (PLAN/EXECUTE)
always sees **raw** text so user voice (and thus persona) is preserved.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.llm_clients.base import BaseLLMProvider

logger = logging.getLogger(__name__)

LEXICON_PATH = Path(__file__).resolve().parent.parent / "lexicon" / "skill_taxonomy.json"

_taxonomy_cache: dict | None = None


@dataclass
class NormalizationResult:
    raw_text: str
    normalized_text: str
    resolved_domain_id: str | None = None
    resolved_action_id: str | None = None
    confidence: float = 0.0
    ambiguity_candidates: list[str] = field(default_factory=list)
    source: str = "keyword"


def normalize_keyword(raw: str, context_hint: str | None = None) -> NormalizationResult:
    """Keyword/fuzzy lexicon match. Zero LLM, instant, always runs.

    ``normalized_text`` is the raw input unchanged -- the keyword path does not
    rewrite. ``source`` is ``"keyword"``.
    """
    if not raw or not raw.strip():
        return NormalizationResult(raw_text=raw, normalized_text="", confidence=0.0)

    text_lower = raw.strip().lower()
    taxonomy = _load_taxonomy()

    domain_result = _match_axis(text_lower, taxonomy, "task_domains", "domain_id", context_hint)
    action_result = _match_axis(text_lower, taxonomy, "action_types", "action_id", context_hint)

    matched = domain_result.matched or action_result.matched
    confidence = max(domain_result.confidence, action_result.confidence) if matched else 0.0

    return NormalizationResult(
        raw_text=raw,
        normalized_text=raw,
        resolved_domain_id=domain_result.domain_id,
        resolved_action_id=action_result.action_id,
        confidence=confidence,
        ambiguity_candidates=domain_result.ambiguity + action_result.ambiguity,
        source="keyword",
    )


def normalize_llm_rewrite(raw: str, provider: BaseLLMProvider, model: str) -> str:
    """Optional LLM canonical rewrite (opt-in per tier). Returns rewritten text.

    On any error, returns the raw text unchanged -- normalization is a sidecar,
    never a gate. The caller sets ``NormalizationResult.source`` to
    ``"llm_keyword"`` when this actually runs.
    """
    if not raw or not raw.strip():
        return raw
    try:
        return provider.complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite the following text to a single, concise, canonical English "
                        "sentence that captures its functional intent. Discard filler words, "
                        "emoji, and marketing language. Preserve the specific technical meaning. "
                        "Output ONLY the rewritten sentence."
                    ),
                },
                {"role": "user", "content": raw},
            ],
            model=model,
            temperature=0.0,
        ).strip()
    except Exception:
        logger.exception("LLM normalization rewrite failed — returning raw text")
        return raw


class _AxisMatchResult:
    def __init__(
        self,
        domain_id: str | None = None,
        action_id: str | None = None,
        matched: bool = False,
        confidence: float = 0.0,
        ambiguity: list[str] | None = None,
    ) -> None:
        self.domain_id = domain_id
        self.action_id = action_id
        self.matched = matched
        self.confidence = confidence
        self.ambiguity = ambiguity or []


def _match_axis(
    text_lower: str,
    taxonomy: dict,
    axis: str,
    id_field: str,
    context_hint: str | None,
) -> _AxisMatchResult:
    entries = taxonomy.get(axis, [])
    candidates: list[tuple[dict, str, str]] = []

    for entry in entries:
        keywords = entry.get("matching_keywords", [])
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue
            if text_lower == kw_lower:
                candidates.append((entry, "exact", kw))
            elif _levenshtein(text_lower, kw_lower) <= 2:
                candidates.append((entry, "fuzzy", kw))
            elif text_lower in kw_lower or kw_lower in text_lower:
                candidates.append((entry, "substring", kw))

    if not candidates:
        return _AxisMatchResult()

    exact = [c for c in candidates if c[1] == "exact"]
    fuzzy = [c for c in candidates if c[1] == "fuzzy"]
    substring = [c for c in candidates if c[1] == "substring"]

    if exact:
        best = _disambiguate(exact, context_hint)
        ambiguity = [c[0].get(id_field, "") for c in exact if c != best]
        return _AxisMatchResult(
            domain_id=best[0].get("domain_id"),
            action_id=best[0].get("action_id"),
            matched=True,
            confidence=1.0,
            ambiguity=ambiguity,
        )
    if fuzzy:
        best = _disambiguate(fuzzy, context_hint)
        ambiguity = [c[0].get(id_field, "") for c in fuzzy if c != best]
        dist = min(_levenshtein(text_lower, c[2].lower()) for c in fuzzy)
        conf = max(0.5, 0.95 - (dist * 0.075))
        return _AxisMatchResult(
            domain_id=best[0].get("domain_id"),
            action_id=best[0].get("action_id"),
            matched=True,
            confidence=conf,
            ambiguity=ambiguity,
        )
    best = _disambiguate(substring, context_hint)
    ambiguity = [c[0].get(id_field, "") for c in substring if c != best]
    return _AxisMatchResult(
        domain_id=best[0].get("domain_id"),
        action_id=best[0].get("action_id"),
        matched=True,
        confidence=0.5,
        ambiguity=ambiguity,
    )


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def _disambiguate(candidates: list, context_hint: str | None) -> tuple:
    if len(candidates) <= 1:
        return candidates[0]
    return candidates[0]


def _load_taxonomy() -> dict:
    global _taxonomy_cache
    if _taxonomy_cache is not None:
        return _taxonomy_cache
    try:
        _taxonomy_cache = json.loads(LEXICON_PATH.read_text())
        logger.info(
            "Loaded skill taxonomy: %s entries",
            sum(len(v) for v in _taxonomy_cache.values() if isinstance(v, list)),
        )
    except Exception:
        logger.exception("Failed to load taxonomy from %s", LEXICON_PATH)
        _taxonomy_cache = {}
    return _taxonomy_cache
