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
    from models import GitHubIssueSummary
    from ports import PRPort

logger = logging.getLogger("hydraflow.escalation_reconcile")

#: Label a *programmatic* closer stamps on an escalation issue BEFORE closing
#: it, so the shared reconciler can tell a bot/factory close from a human/
#: external one (#9437). This is the one, shared bot-close marker: there is
#: exactly one predicate (:func:`is_bot_close`) and one constant across every
#: adopting trust loop. The pre-#9437 mechanism the issue references
#: (``HITL_AUTO_RESOLVED_LABEL`` in ``src/hitl_stale_insight.py``, hardening
#: #8996) never landed — that module and constant no longer exist — so this
#: realises the intended "shared marker" against the signal the reconciler can
#: actually obtain: labels on the closed-issue dict.
BOT_CLOSE_MARKER_LABEL = "hydraflow-auto-resolved"


async def stamp_and_close(prs: PRPort, issue_number: int) -> None:
    """Stamp :data:`BOT_CLOSE_MARKER_LABEL` on *issue_number*, then close it.

    The one shared choke point every PROGRAMMATIC escalation-closer routes
    through (#10095 — activates the #9437 guard, which was landed dormant:
    nothing stamped the marker). Label-before-close so the very next
    ``list_closed_issues_by_label`` read — this tick or a later one — always
    observes both together, letting :func:`is_bot_close` tell this apart
    from a human/external close.

    Callers: ``IssueDecomposer.create_epic_from_result`` (the
    superseded-by-decompose close of the source issue — reachable for a
    ``hitl-escalation``-labeled subject via
    ``preflight.decompose_terminal.decompose_or_escalate``). NEVER call this
    for a close a human initiated (e.g. via the GitHub UI, or an
    intentional dedup-key reset) — that path must keep re-arming the
    tracker, which is exactly what :meth:`EscalationReconciler.reconcile_closed`
    still does when the marker is absent.
    """
    await prs.add_labels(issue_number, [BOT_CLOSE_MARKER_LABEL])
    await prs.close_issue(issue_number)


def is_bot_close(issue: GitHubIssueSummary | dict[str, object]) -> bool:
    """Whether *issue* was closed by a programmatic/bot path, not a human.

    Detected via :data:`BOT_CLOSE_MARKER_LABEL` on the issue dict — the only
    per-close signal the reconciler can obtain, since ``GitHubIssueSummary``
    carries no ``closed_by``/actor/``state_reason``. ``PRManager
    .list_closed_issues_by_label`` projects ``labels`` on the closed listing
    (#8996 — originally label-free by default, #9943), so this predicate is
    load-bearing there; other callers that pass a plain dict with no
    ``labels`` key still fall open per the paragraph below.

    Fail-open toward the pre-#9437 contract: when the marker is ABSENT — which
    includes any case where labels are simply not present on a closed issue —
    the close is treated as human, and the caller drops the dedup key so the
    detector may re-fire, exactly as before this guard. We only ever RETAIN
    the key on a *positive* bot signal; an unknown/unavailable signal never
    starts silently retaining keys everywhere.
    """
    labels = issue.get("labels") or []
    if not isinstance(labels, list):
        return False
    return any(
        isinstance(lbl, dict) and lbl.get("name") == BOT_CLOSE_MARKER_LABEL
        for lbl in labels
    )


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
        """Drop dedup keys + counters for HUMAN-closed escalations.

        A *human/external* close is the intentional reset signal: drop the
        dedup key + attempt counter so the detector may re-fire (the pre-#9437
        contract). A *bot/programmatic* close — one stamped with
        :data:`BOT_CLOSE_MARKER_LABEL` before closing — must NOT reset dedup:
        a premature programmatic close of a subject that is still detected at
        HEAD would otherwise re-arm the tracker and refile a duplicate on the
        next tick (#9437).

        The guard is applied UNIFORMLY — no per-loop opt-out flag. All ~8
        adopting reconcilers want the same contract (never refile a duplicate
        on a bot close), it matches the issue intent ("generalize ... across
        the loops"), and the marker is absent from today's closes, so the
        observable behaviour is unchanged until a programmatic closer starts
        stamping it. A constructor flag would add branching for no sibling that
        genuinely needs different behaviour.
        """
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
            if key not in keep:
                continue
            if is_bot_close(issue):
                # Programmatic close — retain the dedup key so a still-detected
                # subject does not immediately refile a duplicate (#9437).
                continue
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
