"""State mixin for PrRedRepairLoop (#10027: infra-flake retrier + dispatch).

Tracks per-PR bounded attempt counters for both phases:

* Phase 1 — ``gh run rerun --failed`` attempts, capped at
  ``pr_red_rerun_max_attempts``, escalating via a rollup issue once
  exhausted.
* Phase 2 — real-red auto-agent dispatch attempts, capped at
  ``pr_red_repair_dispatch_max_attempts``, escalating via a ``hitl_label``
  add once exhausted.

Both reuse :class:`models.ConvergenceLedger` (the same generic per-issue/PR
attempt-tracking substrate ``SandboxFailureFixerLoop`` migrated onto — see
``state/_sandbox_failure_fixer.py``) under distinct stage names
(``"pr_red_rerun"`` / ``"pr_red_dispatch"``) rather than introducing new
top-level ``StateData`` fields. This is deliberate: ``convergence_ledgers``
is already a registered, persisted, restore-tested field, so a new stage
key needs no ``expected_keys``/persistence changes — the durable,
restart-surviving attempt tracking the spec calls "DedupStore-tracked"
comes for free.

Keyed by PR number (not GitHub Actions run id): the spec's bound is
"bounded ... per PR", so a PR's total budget for each phase is shared
across however many of its checks/attempts are being retried.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import ConvergenceLedger

if TYPE_CHECKING:
    from models import StateData

_STAGE = "pr_red_rerun"
_DISPATCH_STAGE = "pr_red_dispatch"


class PrRedRepairStateMixin:
    """Per-PR bounded rerun/dispatch attempt counters for PrRedRepairLoop."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

    def get_pr_red_rerun_attempts(self, pr_number: int) -> int:
        """Return the current rerun-attempt count for *pr_number* (0 if absent)."""
        cl = self._data.convergence_ledgers.get(str(pr_number))
        return cl.get_attempts(_STAGE) if cl else 0

    def bump_pr_red_rerun_attempts(self, pr_number: int) -> int:
        """Increment and persist the rerun-attempt counter; return the new total."""
        key = str(pr_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=pr_number)
            self._data.convergence_ledgers[key] = cl
        n = cl.increment_attempts(_STAGE)
        self.save()
        return n

    def clear_pr_red_rerun_attempts(self, pr_number: int) -> None:
        """Drop the counter for *pr_number* (e.g. once CI settles green again)."""
        cl = self._data.convergence_ledgers.get(str(pr_number))
        if cl is not None and _STAGE in cl.stage_state:
            cl.stage_state[_STAGE].attempts = 0
            self.save()

    def get_pr_red_dispatch_attempts(self, pr_number: int) -> int:
        """Return the current dispatch-attempt count for *pr_number* (0 if absent)."""
        cl = self._data.convergence_ledgers.get(str(pr_number))
        return cl.get_attempts(_DISPATCH_STAGE) if cl else 0

    def bump_pr_red_dispatch_attempts(self, pr_number: int) -> int:
        """Increment and persist the dispatch-attempt counter; return the new total."""
        key = str(pr_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=pr_number)
            self._data.convergence_ledgers[key] = cl
        n = cl.increment_attempts(_DISPATCH_STAGE)
        self.save()
        return n

    def clear_pr_red_dispatch_attempts(self, pr_number: int) -> None:
        """Drop the counter for *pr_number* (e.g. once CI settles green again)."""
        cl = self._data.convergence_ledgers.get(str(pr_number))
        if cl is not None and _DISPATCH_STAGE in cl.stage_state:
            cl.stage_state[_DISPATCH_STAGE].attempts = 0
            self.save()
