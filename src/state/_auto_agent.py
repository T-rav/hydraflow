"""State mixin for AutoAgentPreflightLoop (spec §3.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import AutoAgentRedriveState, ConvergenceLedger

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

    # --- Escalation TTL re-drive markers (#9719) ---

    def arm_auto_agent_redrive(self, issue: int, ts: str) -> None:
        """Arm the re-drive marker at the exhaustion transition.

        Idempotent: an already-armed marker is a no-op so re-confirmation
        ticks that re-run the exhaustion branch preserve the FIRST exhaustion
        timestamp (the #9716 re-arm trap — a refreshed clock never ages and
        re-drive never fires). A disarmed record (post-re-drive) re-arms with
        a fresh timestamp so each backoff window measures from its own
        exhaustion.
        """
        key = str(issue)
        rec = self._data.auto_agent_redrive.get(key)
        if rec is None:
            self._data.auto_agent_redrive[key] = AutoAgentRedriveState(exhausted_at=ts)
            self.save()
            return
        if rec.exhausted_at is None:
            rec.exhausted_at = ts
            self.save()

    def list_armed_auto_agent_redrives(self) -> list[tuple[int, str, int]]:
        """Return ``(issue, exhausted_at, redrive_count)`` for armed markers."""
        return [
            (int(key), rec.exhausted_at, rec.redrive_count)
            for key, rec in self._data.auto_agent_redrive.items()
            if rec.exhausted_at is not None
        ]

    def get_auto_agent_redrive_count(self, issue: int) -> int:
        rec = self._data.auto_agent_redrive.get(str(issue))
        return rec.redrive_count if rec is not None else 0

    def record_auto_agent_redrive(self, issue: int) -> int:
        """Bump the re-drive count and disarm the marker. Returns new count."""
        key = str(issue)
        rec = self._data.auto_agent_redrive.get(key)
        if rec is None:
            rec = AutoAgentRedriveState()
            self._data.auto_agent_redrive[key] = rec
        rec.redrive_count += 1
        rec.exhausted_at = None
        self.save()
        return rec.redrive_count

    def clear_auto_agent_redrive(self, issue: int) -> None:
        """Drop the re-drive record entirely (reconcile-on-close)."""
        if str(issue) in self._data.auto_agent_redrive:
            del self._data.auto_agent_redrive[str(issue)]
            self.save()

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
