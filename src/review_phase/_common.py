"""Module-level helpers, constants, and dataclasses for the review_phase package.

Split out of the original ``src/review_phase.py`` (T36) so the main
``ReviewPhase`` class file is smaller. Everything here is re-exported from
``review_phase/__init__.py`` for back-compat — external callers continue
to do ``from review_phase import X``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from models import (
    CodeScanningAlert,
    ReviewResult,
    ReviewVerdict,
    Task,
    VisualValidationDecision,
)
from repo_wiki import RepoWikiStore

logger = logging.getLogger("hydraflow.review_phase")

# ``_AdvisorRole`` pins the runner-protocol role contract — used by
# ``_PostVerifyRunner.run`` (T24.5 closed I1+I2: explicit role beats
# substring detection on the prompt). Module-scope so the inner
# ``_PostVerifyRunner`` class body can reference it via closure when
# ``_build_post_verify_runner`` is invoked.
_AdvisorRole = Literal["pre_flight", "mid_flight", "post_verify"]

# T37 — tighten wiki-ingest self-modification detection.
#
# The old detector substring-matched ``src/review_advisor.py`` / ``src/review_phase.py``
# anywhere in the candidate ingest content; a purely descriptive review summary
# that named those paths in passing (e.g., "review found a type-hint gap in
# src/review_advisor.py") would synthesize the pseudo diff header and force
# veto authority on what was a benign wiki entry. Fail-closed but noisy.
#
# These patterns gate synthesis on modification *context*, not bare mentions:
#   1. Already-formed unified-diff headers (real diff content embedded).
#   2. Path inside a fenced ```diff / ```patch block.
#   3. Editorial verbs ("modified", "changed", "edited", "updated", "patched")
#      immediately preceding the path.
# Anything else — prose mention, type-hint reference, file-path-in-error-log —
# is treated as a non-modification mention and does NOT synthesize the header.
# T29's self-mod guard still fires when a real modification context is seen.
#
# #11669: the module names used to be baked into these patterns as
# ``src/(?:review_advisor|review_phase)\.py`` — a third copy of
# ``SELF_MODIFYING_PATHS``, in regex, blind in exactly the same way. It could
# not see ``src/review_phase/_advisors.py`` even though the caller went on to
# intersect the result with the canonical set. The patterns now capture any
# source path in a modification context; deciding whether that path IS the
# advisor's own implementation is ``review_advisor.is_self_modifying_path``'s
# job, and its alone. Context detection here, identity there.
_SOURCE_PATH = r"(src/[\w./-]+\.py)"

_SELF_MOD_SYNTHESIS_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Already-formed diff headers (real diff content embedded in transcript).
    re.compile(rf"diff --git a/{_SOURCE_PATH}"),
    re.compile(rf"\+\+\+ b/{_SOURCE_PATH}"),
    re.compile(rf"--- a/{_SOURCE_PATH}"),
    # Fenced patch / diff block containing the path.
    re.compile(rf"```(?:diff|patch)\b[^`]*?{_SOURCE_PATH}", re.DOTALL),
    # Editorial verbs immediately before the path:
    # "modified src/...", "edited src/...", "updated src/...", "patched src/..."
    re.compile(
        r"\b(?:modif(?:y|ied|ies|ying)|chang(?:e|ed|es|ing)|"
        r"edit(?:ed|s|ing)?|update(?:d|s|ing)?|"
        rf"patch(?:ed|es|ing)?|refactor(?:ed|s|ing)?)\s+[`'\"]*{_SOURCE_PATH}",
        re.IGNORECASE,
    ),
)


def _detect_self_modification_context(transcript: str) -> list[str]:
    """Return the sorted set of source paths that appear in a *modification
    context* within ``transcript`` (not a benign mention).

    Context only — the returned paths are candidates, not verdicts. Callers
    decide which of them belong to the advisor's own implementation via
    ``review_advisor.is_self_modifying_path``, so this detector never has to
    carry a second copy of the module list.

    Empty list means no pseudo diff header should be synthesized — the
    candidate content does not look like it's describing real changes to any
    source file at all.
    """
    detected: set[str] = set()
    for pattern in _SELF_MOD_SYNTHESIS_PATTERNS:
        for match in pattern.finditer(transcript):
            detected.add(match.group(1))
    return sorted(detected)


def _run_fallback_ingest_review(
    *,
    tracked_store: RepoWikiStore,
    worktree_path: Path,
    repo: str,
    issue_number: int,
    summary: str,
    path_prefix: str,
) -> None:
    """Sync wrapper for the fallback review-ingest path.

    Module-level so it can be dispatched via ``asyncio.to_thread`` — the
    sync ``git commit`` in ``commit_pending_entries`` would otherwise
    stall the event loop (ADR-0001).
    """
    from repo_wiki_ingest import ingest_from_review  # noqa: PLC0415

    count = ingest_from_review(
        tracked_store, repo, issue_number, summary, git_backed=True
    )
    if count:
        tracked_store.commit_pending_entries(
            worktree_path=worktree_path,
            phase="review",
            issue_number=issue_number,
            path_prefix=path_prefix,
        )


@dataclass(slots=True)
class ReviewGuardContext:
    """Successful result from _run_initial_guards."""

    task: Task
    workspace_path: Path


@dataclass(slots=True)
class PreReviewContext:
    """Artifacts captured before running the reviewer."""

    diff: str
    visual_decision: VisualValidationDecision | None
    code_scanning_alerts: list[CodeScanningAlert] | None


# Marker substrings indicating a ReviewResult that did NOT reach a real
# verdict and therefore must NOT be cached. Caching these as
# has_blocking=False would silently let a non-reviewed PR satisfy the
# downstream gate.
_NON_VERDICT_SUMMARY_MARKERS: tuple[str, ...] = (
    "stopped",
    "Issue not found",
    "Merge conflicts with main",
    "Review failed due to unexpected error",
)


def _is_meaningful_verdict(result: ReviewResult) -> bool:
    """Return True if *result* represents a real review decision worth caching.

    Skips:
      - COMMENT verdicts (advisory only, no decision)
      - results whose summary contains a non-verdict marker substring
        (stopped, infrastructure error, missing issue, merge conflict)

    Keeps:
      - APPROVE / REQUEST_CHANGES with a normal summary

    Used by ReviewPhase.review_prs to gate the review_stored cache
    write so a no-real-review result cannot poison the downstream
    READY-stage precondition gate.
    """
    if result.verdict == ReviewVerdict.COMMENT:
        return False
    summary = result.summary or ""
    return not any(marker in summary for marker in _NON_VERDICT_SUMMARY_MARKERS)
