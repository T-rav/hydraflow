"""State mixin for SandboxFailureFixerLoop.

Tracks per-PR auto-fix attempts so the loop can cap retries and escalate
to ``sandbox-hitl`` when the auto-agent fails to land a fix in
``auto_agent_max_attempts`` runs. Keys are stringified PR numbers (matches
the JSON-friendly storage convention used by the other attempt counters).

NOTE: sandbox_failure_fixer_attempts migrated to
convergence_ledgers[str(pr_number)].stage_state["sandbox_fix"].attempts
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import ConvergenceLedger

if TYPE_CHECKING:
    from models import StateData


class SandboxFailureFixerStateMixin:
    """Per-PR auto-fix attempt counter for SandboxFailureFixerLoop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_sandbox_failure_fixer_attempts(self, pr_number: int) -> int:
        """Return the current attempt count for *pr_number* (0 if absent)."""
        cl = self._data.convergence_ledgers.get(str(pr_number))
        return cl.get_attempts("sandbox_fix") if cl else 0

    def bump_sandbox_failure_fixer_attempts(self, pr_number: int) -> int:
        """Increment and persist the attempt counter; return the new total."""
        key = str(pr_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=pr_number)
            self._data.convergence_ledgers[key] = cl
        n = cl.increment_attempts("sandbox_fix")
        self.save()
        return n

    def clear_sandbox_failure_fixer_attempts(self, pr_number: int) -> None:
        """Drop the counter for *pr_number* (e.g. after PR closure)."""
        cl = self._data.convergence_ledgers.get(str(pr_number))
        if cl is not None and "sandbox_fix" in cl.stage_state:
            cl.stage_state["sandbox_fix"].attempts = 0
            self.save()
