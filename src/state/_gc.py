"""Per-issue state garbage collection (#9905).

``state.json`` accumulates per-issue entries whose cleanup hooks only fire
on the happy path: ``clear_adversarial_state`` runs on a subset of plan-phase
exits and ``clear_convergence_ledger`` only in the post-merge handler, so
issues terminated any other way (manual close, HITL close, supersede) strand
their entries forever. Observed 6.03 MB of ``adversarial_states`` across 96
issues in a 7.1 MB state file.

The prune is a catch-all sweep driven by GitHub truth: the caller passes the
set of currently-open issue numbers and every entry keyed by an issue outside
that set is dropped. Fail-closed by contract — callers must NOT invoke this
with an empty set (an API fault returning zero issues must skip the sweep,
not wipe the state).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData

logger = logging.getLogger("hydraflow.state")

# Per-issue dicts safe to prune when the issue is no longer open. Every
# field here is keyed by str(issue_number) via StateTracker._key. Fields
# keyed by anything else (worker name, PR branch, stream name) must never
# be listed.
#
# Attempt-cap close-to-clear contract (#9723 Fix J): a closed issue's burned
# attempt budget must not leak into a reopened/re-filed issue. The three
# attempt counters are covered here — ``issue_attempts`` directly,
# review attempts inside ``convergence_ledgers`` stage state, and
# ``hitl_summary_failures`` directly.
#
# #10083 follow-up: the #9723 audit only chased down the fields a prior PR
# happened to touch. A full sweep of every str(issue_number)-keyed
# StateTracker field (tests/regressions/test_issue_10083_gc_sweep.py ::
# test_every_issue_keyed_field_is_classified enforces this structurally —
# see that file for the field-by-field classification) turned up two more
# gaps of the exact same shape as #9723's:
#
# * ``route_back_counts`` / ``review_orphan_strikes`` /
#   ``review_orphan_requeues`` — burned route-back and review-orphan
#   penalty budget, same "attempt cap" risk class as ``issue_attempts``.
# * ``hitl_origins`` / ``hitl_causes`` / ``hitl_visual_evidence`` —
#   siblings of ``hitl_summaries``/``hitl_summary_failures`` inside
#   ``HITLStateMixin.clear_hitl_state``; only two of the five fields that
#   method clears together had made it into this sweep.
# * ``diagnostic_attempts`` / ``diagnosis_severities`` — siblings of
#   ``escalation_contexts`` inside ``DiagnosticStateMixin.clear_diagnostic_state``;
#   only one of the three fields that method clears together had made it
#   into this sweep.
_ISSUE_SCOPED_FIELDS = (
    "adversarial_states",
    "convergence_ledgers",
    "diagnosis_severities",
    "diagnostic_attempts",
    "escalation_contexts",
    "hitl_causes",
    "hitl_origins",
    "hitl_summaries",
    "hitl_summary_failures",
    "hitl_visual_evidence",
    "issue_attempts",
    "review_orphan_requeues",
    "review_orphan_strikes",
    "route_back_counts",
)


class StateGCMixin:
    """Mixin for pruning per-issue state entries for closed issues."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def prune_issue_scoped_state(self, live_issue_numbers: set[int]) -> dict[str, int]:
        """Drop per-issue entries whose issue is not in *live_issue_numbers*.

        Returns ``{field_name: removed_count}`` for fields that shrank.
        A falsy *live_issue_numbers* is a no-op: an empty keep-set is
        indistinguishable from a failed GitHub listing, and pruning against
        it would wipe every in-flight issue's state.
        """
        if not live_issue_numbers:
            return {}
        live_keys = {str(n) for n in live_issue_numbers}
        removed: dict[str, int] = {}
        for field in _ISSUE_SCOPED_FIELDS:
            bucket: dict[str, object] = getattr(self._data, field)
            stale = [
                key
                for key in bucket
                if key not in live_keys and key.lstrip("-").isdigit()
            ]
            for key in stale:
                bucket.pop(key, None)
            if stale:
                removed[field] = len(stale)
        if removed:
            self.save()
        return removed
