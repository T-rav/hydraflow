"""The HITL cause taxonomy: keywords, enum, priority, and classification.

The keyword tuples and ``_classify_cause`` live here WITH the methods that
read them. A constant left behind while its only consumer moved is the
classic split defect: every call raises ``NameError`` inside a broad
handler and reports a plausible-looking failure instead (#11658).

``_effective_cause`` is the runtime refinement of the label-derived cause
(a PR that reports a conflict beats whatever the HITL text said), and
``_is_merge_conflict`` is the keyword test the round loop sorts on. They
change together with the vocabulary above them.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ports import PRPort


logger = logging.getLogger("hydraflow.pr_unsticker")


# Keywords that indicate a merge conflict cause
_MERGE_CONFLICT_KEYWORDS = ("merge conflict", "conflict")

# Keywords for CI / quality failures
_CI_FAILURE_KEYWORDS = (
    "ci fail",
    "ci_fail",
    "check fail",
    "test fail",
    "lint fail",
    "type",
)

# Keywords for CI timeout (checked before CI failure since cause may contain both)
_CI_TIMEOUT_KEYWORDS = ("timeout", "timed out")

# Keywords for review fix cap exceeded
_REVIEW_CAP_KEYWORDS = ("review fix", "fix attempt", "fix cap", "review cap")


class FailureCause(StrEnum):
    """Classification of HITL escalation causes."""

    MERGE_CONFLICT = "merge_conflict"
    CI_TIMEOUT = "ci_timeout"
    CI_FAILURE = "ci_failure"
    REVIEW_FIX_CAP = "review_fix_cap"
    GENERIC = "generic"


# Priority order: lower index = processed first
_CAUSE_PRIORITY = {
    FailureCause.MERGE_CONFLICT: 0,
    FailureCause.CI_TIMEOUT: 1,
    FailureCause.CI_FAILURE: 2,
    FailureCause.REVIEW_FIX_CAP: 3,
    FailureCause.GENERIC: 4,
}


def _classify_cause(cause: str) -> FailureCause:
    """Classify a free-text HITL cause into a FailureCause enum value."""
    lower = cause.lower()
    if any(kw in lower for kw in _MERGE_CONFLICT_KEYWORDS):
        return FailureCause.MERGE_CONFLICT
    # Check timeout before CI failure — cause like "CI failed...: Timeout..."
    # contains both "ci fail" and "timeout" keywords.
    if any(kw in lower for kw in _CI_TIMEOUT_KEYWORDS):
        return FailureCause.CI_TIMEOUT
    if any(kw in lower for kw in _CI_FAILURE_KEYWORDS):
        return FailureCause.CI_FAILURE
    if any(kw in lower for kw in _REVIEW_CAP_KEYWORDS):
        return FailureCause.REVIEW_FIX_CAP
    return FailureCause.GENERIC


class PRUnstickerCauseMixin:
    """The HITL cause taxonomy: keywords, enum, priority, and classification."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``PRUnsticker.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _prs: PRPort

    async def _effective_cause(
        self, cause: FailureCause, pr_number: int | None
    ) -> FailureCause:
        """Override the stored-cause classification with the live merge state.

        A PR that became conflicting *after* its original escalation — e.g. a
        code-complete PR that went DIRTY when the base branch advanced (the
        recurring regenerated-artifact conflict) — carries a stale cause string
        that never mentions a conflict. Routed by that string it would get a
        no-op code fix and stay DIRTY forever. If GitHub reports the PR as
        conflicting now, treat it as a ``MERGE_CONFLICT`` so it is rebased
        first (ADR-0084: rescue stuck PRs).
        """
        if cause == FailureCause.MERGE_CONFLICT or not pr_number or pr_number <= 0:
            return cause
        if await self._prs.get_pr_mergeable(pr_number) is False:
            logger.info(
                "PR #%d is conflicting now — resolving the conflict before the "
                "stored cause (%s)",
                pr_number,
                cause.value,
            )
            return FailureCause.MERGE_CONFLICT
        return cause

    def _is_merge_conflict(self, cause: str) -> bool:
        """Return *True* if *cause* indicates a merge conflict."""
        lower = cause.lower()
        return any(kw in lower for kw in _MERGE_CONFLICT_KEYWORDS)
