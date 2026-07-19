"""State accessors for SkillPromptEvalLoop (spec §4.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class SkillPromptEvalStateMixin:
    """Last-green eval snapshot + per-case repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_skill_prompt_last_green(self) -> dict[str, str]:
        return dict(self._data.skill_prompt_last_green)

    def set_skill_prompt_last_green(self, snap: dict[str, str]) -> None:
        self._data.skill_prompt_last_green = dict(snap)
        self.save()

    def get_skill_prompt_attempts(self, case_id: str) -> int:
        return int(self._data.skill_prompt_attempts.get(case_id, 0))

    def inc_skill_prompt_attempts(self, case_id: str) -> int:
        current = int(self._data.skill_prompt_attempts.get(case_id, 0)) + 1
        attempts = dict(self._data.skill_prompt_attempts)
        attempts[case_id] = current
        self._data.skill_prompt_attempts = attempts
        self.save()
        return current

    def clear_skill_prompt_attempts(self, case_id: str) -> None:
        attempts = dict(self._data.skill_prompt_attempts)
        attempts.pop(case_id, None)
        self._data.skill_prompt_attempts = attempts
        self.save()

    # --- Prompt self-refinement weekly cap (#9724) ---

    def record_refine_proposal(self, now_iso: str) -> None:
        self._data.skill_prompt_refine_proposals.append(now_iso)
        self.save()

    def refine_proposals_last_7d(self, now: datetime) -> int:
        """Count refine proposals inside the rolling 7-day window ending at *now*.

        Timezone contract: *now* MUST be timezone-aware — always pass
        ``datetime.now(UTC)``. The cutoff inherits its tzinfo, so a naive *now*
        would raise ``TypeError`` the moment it meets a stored aware timestamp.
        Stored timestamps are parsed back with ``datetime.fromisoformat``; a
        value written without an offset comes back naive, so each such value is
        normalized to UTC (``replace(tzinfo=UTC)``) before comparison. This keeps
        a naive/aware mix from raising and treats un-offset records as UTC, which
        is what the loop writes (all proposals are recorded as ``now(UTC)``).
        """
        cutoff = now - timedelta(days=7)
        kept: list[str] = []
        for ts in self._data.skill_prompt_refine_proposals:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            if dt > cutoff:
                kept.append(ts)
        if len(kept) != len(self._data.skill_prompt_refine_proposals):
            self._data.skill_prompt_refine_proposals = kept
            self.save()
        return len(kept)

    # --- Telemetry consumption baseline (spec §5) ---

    def get_prompt_efficiency_baseline(self) -> dict[str, dict[str, int]]:
        """Return last tick's `PromptTelemetry.get_source_totals()` snapshot."""
        return {k: dict(v) for k, v in self._data.prompt_efficiency_baseline.items()}

    def set_prompt_efficiency_baseline(
        self, snapshot: dict[str, dict[str, int]]
    ) -> None:
        """Overwrite the stored baseline with *snapshot* (this tick's totals).

        Call AFTER computing trend vs. the previous baseline — this is a
        trailing-window comparison (current tick vs. the immediately
        preceding tick), not a multi-week rolling average.
        """
        self._data.prompt_efficiency_baseline = {
            k: dict(v) for k, v in snapshot.items()
        }
        self.save()
