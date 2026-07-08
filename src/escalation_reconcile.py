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

Safety properties:

- ``reconcile_open`` requires the tick's detection to have COMPLETED —
  callers pass ``active_subjects=None`` on failed/partial scans, which
  skips the pass entirely. Closing on incomplete data would kill real
  escalations and reset their attempt budgets (escalation churn).
- Close-then-clear: state is only cleared when an open escalation was
  actually closed. Some loops share the dedup store with first-pass rollup
  dedup; clearing without a close could re-file those.
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
    """Closed + open escalation reconciliation against a loop's dedup state.

    ``subject`` is everything after the first ``:`` in a dedup key —
    matched against escalation titles by substring, mirroring the historic
    per-loop implementations. Loops whose subjects can prefix-collide
    should pass a stricter ``subject_in_title``.
    """

    def __init__(
        self,
        *,
        prs: PRPort,
        dedup: DedupStore,
        key_prefix: str,
        stuck_label: str,
        clear_attempts: Callable[[str], None],
        subject_in_title: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._prs = prs
        self._dedup = dedup
        self._key_prefix = f"{key_prefix}:"
        self._stuck_label = stuck_label
        self._clear_attempts = clear_attempts
        self._subject_in_title = subject_in_title or (
            lambda subject, title: subject in title
        )

    def _subjects(self) -> dict[str, str]:
        """Map subject → full dedup key for keys owned by this loop."""
        return {
            key.split(":", 1)[1]: key
            for key in self._dedup.get()
            if key.startswith(self._key_prefix)
        }

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
        subjects = self._subjects()
        if not subjects:
            return
        keys = self._dedup.get()
        keep = set(keys)
        for issue in closed:
            title = issue.get("title", "")
            for subject, key in subjects.items():
                if key in keep and self._subject_in_title(subject, title):
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
        subjects = self._subjects()
        stale = {s: k for s, k in subjects.items() if s not in active_subjects}
        if not stale:
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
        for subject, key in stale.items():
            matching = [
                issue
                for issue in open_escalations
                if self._subject_in_title(subject, issue.get("title", ""))
            ]
            if not matching:
                continue
            subject_closed = 0
            for issue in matching:
                number = issue.get("number")
                if not number:
                    continue
                try:
                    await self._prs.post_comment(
                        number,
                        f"`{subject}` is no longer detected at HEAD — the gap "
                        f"was fixed by a later change or was a false "
                        f"positive. Auto-closing; the detector re-escalates "
                        f"fresh if it recurs.",
                    )
                    await self._prs.close_issue(number)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "reconcile_open: failed to close escalation #%s",
                        number,
                        exc_info=True,
                    )
                    continue
                subject_closed += 1
                logger.info(
                    "Auto-closed stale escalation #%s (%s no longer detected)",
                    number,
                    subject,
                )
            if subject_closed:
                # Close-then-clear: state resets only after an actual close;
                # a failed close leaves key + counter for the next tick.
                closed_count += subject_closed
                keys = keys - {key}
                self._clear_attempts(subject)
        if closed_count:
            self._dedup.set_all(keys)
        return closed_count
