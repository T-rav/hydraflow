"""Shared escalation reconciliation for trust loops (spec §3.2 extension).

Every trust loop files ``hitl-escalation`` issues after N failed repair
attempts and tracks them with dedup keys shaped ``{loop}:{subject}`` plus a
per-subject attempt counter. Two lifecycle paths need reconciling:

- **Closed** (existing contract): a human closed the escalation → drop the
  dedup key and reset the counter so the detector may re-fire. Previously
  copy-pasted across five loops as ``_reconcile_closed_escalations``.
- **Open** (new): the gap no longer exists at HEAD — a later PR fixed it,
  or the finding was a false positive. Without this path an escalation is
  a dead letter until a human notices (#9618 sat six days). Each tick the
  loop passes its currently-detected subject set; any open escalation whose
  subject is absent gets closed with an explanatory comment, and its dedup
  key + attempt counter are cleared so a genuine re-occurrence escalates
  fresh.

Subjects are parsed FROM ISSUE TITLES via the loop-supplied
``subject_from_title`` — never discovered from dedup keys. Recovery paths
(e.g. fake_coverage's ``_clear_rollup_state``) erase the dedup key on the
very tick the gap disappears; key-driven discovery would orphan the open
escalation forever.

Safety properties:

- ``reconcile_open`` requires the tick's detection to have COMPLETED —
  callers pass ``active_subjects=None`` on failed/partial scans, which
  skips the pass entirely. Closing on incomplete data would kill real
  escalations and reset their attempt budgets (escalation churn).
- Close-then-clear: dedup/attempt state resets only after an actual
  successful close; a failed close leaves everything for the next tick.
- Unparseable titles (operator-created issues carrying the label) are
  left untouched.
- Port errors are swallowed (skip, retry next tick) — reconciliation is
  hygiene, never worth crashing a work cycle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from dedup_store import DedupStore
    from ports import PRPort

logger = logging.getLogger("hydraflow.escalation_reconcile")


class EscalationReconciler:
    """Closed + open escalation reconciliation for one trust loop.

    ``subject_from_title`` parses the loop's escalation-title format back
    to the subject (the part after ``{key_prefix}:`` in dedup keys);
    returning ``None`` marks a title as not-ours (skipped).
    """

    def __init__(
        self,
        *,
        prs: PRPort,
        dedup: DedupStore,
        key_prefix: str,
        stuck_label: str,
        clear_attempts: Callable[[str], None],
        subject_from_title: Callable[[str], str | None],
    ) -> None:
        self._prs = prs
        self._dedup = dedup
        self._key_prefix = key_prefix
        self._stuck_label = stuck_label
        self._clear_attempts = clear_attempts
        self._subject_from_title = subject_from_title

    def _key(self, subject: str) -> str:
        return f"{self._key_prefix}:{subject}"

    async def reconcile_closed(self) -> None:
        """Drop dedup keys + counters for human-closed escalations."""
        try:
            closed = await self._prs.list_closed_issues_by_label(
                self._stuck_label, limit=100
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "reconcile_closed: could not list closed %s issues",
                self._stuck_label,
                exc_info=True,
            )
            return
        keys = self._dedup.get()
        keep = set(keys)
        for issue in closed:
            subject = self._subject_from_title(issue.get("title", ""))
            if subject is None:
                continue
            key = self._key(subject)
            if key in keep:
                keep.discard(key)
                self._clear_attempts(subject)
        if keep != keys:
            self._dedup.set_all(keep)

    async def reconcile_open(self, active_subjects: set[str] | None) -> int:
        """Close open escalations whose gap is no longer detected.

        *active_subjects* is the set of subjects the loop detected THIS
        tick; ``None`` means detection failed or was partial — skip.
        Returns the number of escalations closed.
        """
        if active_subjects is None:
            return 0
        try:
            open_escalations = await self._prs.list_issues_by_label(self._stuck_label)
        except Exception:  # noqa: BLE001
            logger.debug(
                "reconcile_open: could not list open %s issues",
                self._stuck_label,
                exc_info=True,
            )
            return 0
        closed_count = 0
        keys = self._dedup.get()
        for issue in open_escalations:
            title = issue.get("title", "")
            number = issue.get("number")
            subject = self._subject_from_title(title)
            if subject is None or not number:
                continue
            if subject in active_subjects:
                continue
            try:
                await self._prs.post_comment(
                    number,
                    f"`{subject}` is no longer detected at HEAD — the gap "
                    f"was fixed by a later change or was a false positive. "
                    f"Auto-closing; the detector re-escalates fresh if it "
                    f"recurs.",
                )
                await self._prs.close_issue(number)
            except Exception:  # noqa: BLE001
                # Close-then-clear: leave key + counter for the next tick.
                logger.warning(
                    "reconcile_open: failed to close escalation #%s",
                    number,
                    exc_info=True,
                )
                continue
            closed_count += 1
            keys = keys - {self._key(subject)}
            self._clear_attempts(subject)
            logger.info(
                "Auto-closed stale escalation #%s (%s no longer detected)",
                number,
                subject,
            )
        if closed_count:
            self._dedup.set_all(keys)
        return closed_count
