"""State mixin for AutoAgentPreflightLoop (spec §3.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import ConvergenceLedger

if TYPE_CHECKING:
    from models import StateData


class AutoAgentStateMixin:
    """Per-issue attempt counter + per-day spend tracker."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_auto_agent_attempts(self, issue: int) -> int:
        cl = self._data.convergence_ledgers.get(str(issue))
        return cl.get_attempts("auto_agent") if cl else 0

    def bump_auto_agent_attempts(self, issue: int) -> int:
        key = str(issue)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=issue)
            self._data.convergence_ledgers[key] = cl
        n = cl.increment_attempts("auto_agent")
        self.save()
        return n

    def clear_auto_agent_attempts(self, issue: int) -> None:
        cl = self._data.convergence_ledgers.get(str(issue))
        if cl is not None and "auto_agent" in cl.stage_state:
            cl.stage_state["auto_agent"].attempts = 0
            self.save()

    def refund_auto_agent_attempt(self, issue: int) -> int:
        """Decrement the attempt counter by one (floor 0).

        Used when an attempt was bumped but no real work happened — e.g. an API
        credit/session limit aborted the spawn (ADR-0084). Refunding keeps a
        transient outage from consuming the issue's attempt budget and wrongly
        exhausting it to ``human-required`` across repeated outages.
        """
        cl = self._data.convergence_ledgers.get(str(issue))
        if cl is None:
            return 0
        rec = cl.stage_state.get("auto_agent")
        if rec is None:
            return 0
        rec.attempts = max(0, rec.attempts - 1)
        self.save()
        return rec.attempts

    def get_auto_agent_daily_spend(self, date_iso: str) -> float:
        return float(self._data.auto_agent_daily_spend.get(date_iso, 0.0))

    def add_auto_agent_daily_spend(self, date_iso: str, usd: float) -> float:
        current = float(self._data.auto_agent_daily_spend.get(date_iso, 0.0))
        new_total = current + usd
        spend = dict(self._data.auto_agent_daily_spend)
        spend[date_iso] = new_total
        # Prune entries older than ~90 days to bound state size — the dashboard
        # only reads the rolling 7d window from this cache, and the JSONL audit
        # remains the source of truth for older queries (spec §6.3).
        if len(spend) > 90:
            keep_keys = sorted(spend.keys())[-90:]
            spend = {k: spend[k] for k in keep_keys}
        self._data.auto_agent_daily_spend = spend
        self.save()
        return new_total
