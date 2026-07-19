"""State accessors for SkillPromptEvalLoop (spec §4.6)."""

from __future__ import annotations

from datetime import datetime, timedelta
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
        cutoff = now - timedelta(days=7)
        kept = [
            ts
            for ts in self._data.skill_prompt_refine_proposals
            if datetime.fromisoformat(ts) > cutoff
        ]
        if len(kept) != len(self._data.skill_prompt_refine_proposals):
            self._data.skill_prompt_refine_proposals = kept
            self.save()
        return len(kept)
