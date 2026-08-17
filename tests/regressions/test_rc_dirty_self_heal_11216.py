"""Regression pins for #11216: DIRTY RC promotion PRs self-heal.

A DIRTY rc/* promotion PR used to sit until a human ran the recipe by
hand — performed three times on 2026-08-15/16 by the supervisor, which is
what made it a standing issue. The loop now runs that recipe itself:
corroborate a genuine conflict, merge the base branch in, let CI re-run,
promote on the next cadence tick.

Pins:
1. DIRTY (mergeable False) → heals, MERGE method (never rebase — the
   #11045 divergence lesson), comments once, returns conflict_healed.
2. Non-conflicting merge failure (True/None/unreadable) → legacy
   merge_failed, branch untouched. Never heal on a guess.
3. Attempts are bounded per RC branch; beyond the cap it escalates to the
   human instead of looping.
4. Kill-switch honored.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from staging_promotion_loop import StagingPromotionLoop

RC = "rc/2026-08-17-0900"


def _loop(
    *,
    mergeable: object,
    attempts: int = 0,
    enabled: bool = True,
    update_ok: bool = True,
) -> StagingPromotionLoop:
    loop = object.__new__(StagingPromotionLoop)
    loop._config = HydraFlowConfig(
        rc_conflict_heal_enabled=enabled, rc_conflict_heal_max_attempts=2
    )
    get_mergeable = (
        AsyncMock(side_effect=mergeable)
        if isinstance(mergeable, Exception)
        else AsyncMock(return_value=mergeable)
    )
    loop._prs = SimpleNamespace(
        get_pr_mergeable=get_mergeable,
        update_pr_branch=AsyncMock(return_value=update_ok),
        post_comment=AsyncMock(),
    )
    bumped: list[str] = []
    loop._state = SimpleNamespace(
        get_rc_conflict_heal_attempts=lambda _b: attempts,
        bump_rc_conflict_heal_attempts=bumped.append,
    )
    loop._bumped = bumped  # type: ignore[attr-defined]
    return loop


@pytest.mark.asyncio
async def test_dirty_pr_heals_with_merge_not_rebase() -> None:
    loop = _loop(mergeable=False)
    assert await loop._maybe_heal_dirty_promotion(500, RC) is True
    loop._prs.update_pr_branch.assert_awaited_once_with(500, method="merge")
    loop._prs.post_comment.assert_awaited_once()
    assert loop._bumped == [RC]


@pytest.mark.asyncio
async def test_non_conflicting_failure_never_touches_the_branch() -> None:
    for state in (True, None):
        loop = _loop(mergeable=state)
        assert await loop._maybe_heal_dirty_promotion(500, RC) is False
        loop._prs.update_pr_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreadable_state_never_heals_on_a_guess() -> None:
    loop = _loop(mergeable=RuntimeError("gh down"))
    assert await loop._maybe_heal_dirty_promotion(500, RC) is False
    loop._prs.update_pr_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_attempts_are_bounded_per_branch() -> None:
    loop = _loop(mergeable=False, attempts=2)  # cap reached
    assert await loop._maybe_heal_dirty_promotion(500, RC) is False
    loop._prs.update_pr_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_kill_switch_disables_the_heal() -> None:
    loop = _loop(mergeable=False, enabled=False)
    assert await loop._maybe_heal_dirty_promotion(500, RC) is False
    loop._prs.get_pr_mergeable.assert_not_awaited()
