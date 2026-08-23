"""Prompt inputs for ``AgentRunner``.

Extracted VERBATIM from ``src/agent.py`` (god-class decomposition,
Refs #11547) as a mixin.

One concern: the untrusted-text material the implement prompt quotes — recurring
review feedback, open escalations, and the two truncation helpers that keep a
long issue thread from swamping the prompt budget.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from base_runner import BaseRunner
from exception_classify import is_likely_bug
from review_insights import (
    ReviewInsightStore,
    get_common_feedback_section,
    get_escalation_data,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from context_cache import ContextSectionCache


logger = logging.getLogger("hydraflow.agent")


class AgentPromptContextMixin(BaseRunner):
    """Prompt inputs for ``AgentRunner``.

    Inherits ``BaseRunner``: these slices call ``self._execute`` /
    ``self._build_command`` and one delegates to ``super()._verify_quality``,
    so the base has to sit in the MIXIN's own MRO, not only in
    ``AgentRunner``'s. It also keeps the runner-scoped gates enumerating every
    file that holds a spawn site.
    """

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``AgentRunner.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _context_cache: ContextSectionCache
    _insights: ReviewInsightStore

    def _get_review_feedback_section(self) -> str:
        """Build a common review feedback section from recent review data.

        Returns an empty string if no data is available or on any error.
        """
        try:
            reviews_path = self._config.repo_memory_dir / "reviews.jsonl"

            def _load_feedback(_cfg: HydraFlowConfig) -> str:
                recent = self._insights.load_recent(self._config.review_insight_window)
                return get_common_feedback_section(recent)

            feedback, _hit = self._context_cache.get_or_load(
                key="common_review_feedback",
                source_path=reviews_path,
                loader=_load_feedback,
            )
            return feedback
        except Exception as exc:  # noqa: BLE001
            if is_likely_bug(exc):
                raise
            return ""

    def _get_escalation_data(self) -> list[dict[str, str | int | list[str]]]:
        """Return escalation data for recurring feedback categories.

        Uses the context cache with a separate key. The cache stores
        JSON-serialized data since the cache interface is typed for strings.
        Returns an empty list on any error.
        """
        try:
            reviews_path = self._config.repo_memory_dir / "reviews.jsonl"

            def _load_escalations(_cfg: HydraFlowConfig) -> str:
                recent = self._insights.load_recent(self._config.review_insight_window)
                data = get_escalation_data(
                    recent,
                    threshold=self._config.review_pattern_threshold,
                )
                return json.dumps(data)

            raw, _hit = self._context_cache.get_or_load(
                key="review_escalations",
                source_path=reviews_path,
                loader=_load_escalations,
            )
            if not raw:
                return []
            return json.loads(raw)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return []
        except Exception as exc:  # noqa: BLE001
            if is_likely_bug(exc):
                raise
            return []

    def _summarize_for_prompt(self, text: str, max_chars: int, label: str) -> str:
        """Return text trimmed for prompt efficiency with a traceable note."""
        if len(text) <= max_chars:
            return text

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        cue_lines = [
            ln for ln in lines if re.match(r"^([-*]|\d+\.)\s+", ln) or "## " in ln
        ]
        selected = cue_lines[:10] if cue_lines else lines[:10]
        compact = "\n".join(f"- {ln[:200]}" for ln in selected).strip()
        if not compact:
            compact = text[:max_chars]
        return (
            f"{compact}\n\n"
            f"[{label} summarized from {len(text):,} chars to reduce prompt size]"
        )

    def _truncate_comment_for_prompt(self, text: str) -> str:
        """Return one discussion comment compacted for prompt efficiency."""
        raw = (text or "").strip()
        limit = self._config.max_discussion_comment_chars
        if len(raw) <= limit:
            return raw
        return raw[:limit] + f"\n[Comment truncated from {len(raw):,} chars]"
