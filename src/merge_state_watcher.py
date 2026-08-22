"""MergeStateWatcher — auto-rebase / HITL-escalate conflicting PRs.

When ``mergeable=CONFLICTING`` shows up on an open PR, this worker tries
to fix it the cheap way (``gh pr update-branch``, no LLM). If that does
not resolve the conflict, a factory-owned PR gets one bounded
merge+regen+push attempt via the :class:`pr_autorebase.PRAutoRebase`
actuator (#11595 — GitHub cannot API-update a genuinely CONFLICTING PR,
and per-PR committed generated artifacts make every staging advance
produce one). Only when that also declines is the PR labeled
``hydraflow-hitl`` so the existing ``PRUnsticker`` +
``MergeConflictResolver`` path takes over.

This closes the gap where RC-promotion PRs (cut by ``StagingPromotionLoop``),
dependabot PRs, and out-of-date agent PRs sat indefinitely because nothing
labeled them HITL. Source-agnostic on purpose — same loop covers RC,
dependabot, and agent PRs without each originator reimplementing the fix
(the auto-rebase actuator itself acts only on the factory's own ``agent/*``
head branches).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from ports import PRPort
    from pr_autorebase import PRAutoRebase

logger = logging.getLogger("hydraflow.merge_state_watcher")

# PRs already on these labels are owned by another loop — leave them alone.
SKIP_LABELS = ("hydraflow-review",)


@dataclass(frozen=True)
class ConflictingPR:
    """A single PR that ``gh pr list`` flagged as ``mergeable=CONFLICTING``."""

    number: int
    branch: str = ""
    labels: list[str] = field(default_factory=list)


class MergeStateWatcher:
    """Find conflicting PRs and either rebase them or escalate to HITL."""

    def __init__(
        self,
        *,
        prs: PRPort,
        hitl_label: str,
        autorebase: PRAutoRebase | None = None,
    ) -> None:
        self._prs = prs
        self._hitl_label = hitl_label
        self._autorebase = autorebase

    async def unstick_conflicts(self) -> dict[str, int]:
        """Single cycle: scan, rebase, escalate.

        Returns counters keyed by ``checked``, ``rebased``, ``autorebased``,
        ``escalated``, ``skipped`` for status reporting.
        """
        prs = await self._prs.list_conflicting_prs()
        stats = {
            "checked": 0,
            "rebased": 0,
            "autorebased": 0,
            "escalated": 0,
            "skipped": 0,
        }

        for pr in prs:
            stats["checked"] += 1
            if self._should_skip(pr):
                stats["skipped"] += 1
                logger.debug("Skipping PR #%d (labels=%s)", pr.number, pr.labels)
                continue

            outcome = await self._handle_pr(pr)
            stats[outcome] += 1

        if stats["checked"]:
            logger.info(
                "merge_state_watcher cycle: %s",
                {k: v for k, v in stats.items() if v},
            )
        return stats

    def _should_skip(self, pr: ConflictingPR) -> bool:
        labels = {label.lower() for label in pr.labels}
        if self._hitl_label.lower() in labels:
            return True
        return any(skip.lower() in labels for skip in SKIP_LABELS)

    async def _handle_pr(self, pr: ConflictingPR) -> str:
        """Try to rebase; on failure, escalate. Returns the stats key to bump."""
        try:
            update_ok = await self._prs.update_pr_branch(pr.number)
        except Exception:  # noqa: BLE001
            logger.warning(
                "update_pr_branch raised for PR #%d", pr.number, exc_info=True
            )
            update_ok = False

        if update_ok:
            try:
                still_mergeable = await self._prs.get_pr_mergeable(pr.number)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "get_pr_mergeable raised for PR #%d", pr.number, exc_info=True
                )
                still_mergeable = None
            if still_mergeable is True:
                return "rebased"

        # #11595: the cheap API update cannot resolve a genuine conflict.
        # Give a factory-owned PR one bounded merge+regen+push attempt before
        # escalating; every non-"autorebased" outcome (disarmed kill-switch,
        # non-factory branch, already attempted at this staging head, source
        # conflict, engine failure) falls through to the HITL escalation
        # below, so the actuator can only reduce toil, never hide a PR.
        if self._autorebase is not None:
            try:
                outcome = await self._autorebase.try_autorebase(pr)
            except (OSError, RuntimeError, TimeoutError) as exc:
                # Credit/auth (RuntimeError subclasses) must escape to the
                # owning loop's cycle handler; anything transient degrades to
                # escalation. Likely-bug types propagate uncaught by design.
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "pr_autorebase raised for PR #%d", pr.number, exc_info=True
                )
                outcome = "failed"
            if outcome == "autorebased":
                return "autorebased"

        try:
            await self._prs.add_pr_labels(pr.number, [self._hitl_label])
        except Exception:  # noqa: BLE001
            logger.warning("add_pr_labels failed for PR #%d", pr.number, exc_info=True)
        return "escalated"
