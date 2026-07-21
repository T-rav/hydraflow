"""State mixin for PrRedRepairLoop (#10027 Phase 1: infra-flake retrier).

Tracks per-PR bounded ``gh run rerun --failed`` attempts so the loop can
cap retries at ``pr_red_rerun_max_attempts`` and escalate via a rollup
issue once exhausted. Reuses :class:`models.ConvergenceLedger` (the same
generic per-issue/PR attempt-tracking substrate ``SandboxFailureFixerLoop``
migrated onto — see ``state/_sandbox_failure_fixer.py``) under a distinct
stage name (``"pr_red_rerun"``) rather than introducing a new top-level
``StateData`` field. This is deliberate: ``convergence_ledgers`` is already
a registered, persisted, restore-tested field, so a new stage key needs no
``expected_keys``/persistence changes — the durable, restart-surviving
attempt tracking the spec calls "DedupStore-tracked" comes for free.

Keyed by PR number (not GitHub Actions run id): the spec's bound is
"bounded gh run rerun --failed per PR", so a PR's total rerun budget is
shared across however many of its checks are being retried.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import ConvergenceLedger

if TYPE_CHECKING:
    from models import StateData

_STAGE = "pr_red_rerun"


class PrRedRepairStateMixin:
    """Per-PR bounded infra-flake-rerun attempt counter for PrRedRepairLoop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

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
