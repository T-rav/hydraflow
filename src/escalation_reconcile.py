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
  successful close, persisted per subject; a failed close leaves that
  subject's state for the next tick.
- Unparseable titles (operator-created issues carrying the label) are
  left untouched.
- Port errors PROPAGATE — the caller runs inside a loop cycle whose base
  handler owns error classification (re-raises credit/auth per the
  reraise_on_credit_or_bug rule, reports the rest as a cycle error and
  retries next tick). No broad excepts here (disturbance ratchet); the
  closed-path title parser self-heals any close that half-completed.
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
        closed = await self._prs.list_closed_issues_by_label(
            self._stuck_label, limit=100
        )
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
        open_escalations = await self._prs.list_issues_by_label(self._stuck_label)
        closed_count = 0
        for issue in open_escalations:
            title = issue.get("title", "")
            number = issue.get("number")
            subject = self._subject_from_title(title)
            if subject is None or not number:
                continue
            if subject in active_subjects:
                continue
            await self._prs.post_comment(
                number,
                f"`{subject}` is no longer detected at HEAD — the gap "
                f"was fixed by a later change or was a false positive. "
                f"Auto-closing; the detector re-escalates fresh if it "
                f"recurs.",
            )
            await self._prs.close_issue(number)
            # Close-then-clear, persisted per subject: a later failure
            # propagates to the loop's cycle handler without losing the
            # progress already made this tick.
            closed_count += 1
            self._dedup.set_all(self._dedup.get() - {self._key(subject)})
            self._clear_attempts(subject)
            logger.info(
                "Auto-closed stale escalation #%s (%s no longer detected)",
                number,
                subject,
            )
        return closed_count
