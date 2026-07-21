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
_ISSUE_SCOPED_FIELDS = (
    "adversarial_states",
    "convergence_ledgers",
    "escalation_contexts",
    "hitl_summaries",
    "hitl_summary_failures",
    "issue_attempts",
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
