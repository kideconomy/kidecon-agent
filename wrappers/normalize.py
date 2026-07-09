from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shared.normalizer.normalizer import NormalizationResult
from shared.normalizer.normalizer import normalize_keyword
from shared.normalizer.normalizer import normalize_llm_rewrite

if TYPE_CHECKING:
    from shared.llm_clients.base import BaseLLMProvider

logger = logging.getLogger(__name__)


def normalize(
    raw: str,
    *,
    provider: BaseLLMProvider | None = None,
    llm_rewrite_model: str | None = None,
    do_llm_rewrite: bool = False,
    context_hint: str | None = None,
) -> NormalizationResult:
    """Edge ORIENT normalization sidecar.

    ``normalize_keyword`` always runs (zero LLM, instant). The LLM-rewrite path
    is **opt-in per tier** (``do_llm_rewrite``), uses the user's OpenRouter key
    via the shared LLM factory, and runs only after the keyword path. The
    reasoning LLM (PLAN/EXECUTE) always sees **raw** text -- this is metadata.
    """
    result = normalize_keyword(raw, context_hint=context_hint)
    if do_llm_rewrite and provider is not None and llm_rewrite_model:
        rewritten = normalize_llm_rewrite(raw, provider, llm_rewrite_model)
        if rewritten and rewritten.strip():
            result.normalized_text = rewritten
            result.source = "llm_keyword"
    return result
