"""Regression: streak escalations had no auto-close path (#10015).

StagingPromotionLoop's rc-promotion-stuck escalation (#9867 class) was filed
via bare ``create_issue`` with no resolve path — a green promotion only reset
the consecutive-failure counter, so the HITL escalation stayed open forever
unless a human (or an unrelated PR body saying "Closes #NNNN") closed it.

Pins (#10015):
- The escalation is tracked as a rollup subject
  (``staging_promotion:rc_promotion_stuck``) with a STABLE title.
- The next green promotion closes the escalation issue and clears its
  tracking, alongside the existing ``rc_ci`` rolling-issue resolve.
- A later streak escalates fresh (new issue), not into the dead letter.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import evidence_pack
import subprocess_util
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from models import PRInfo
from staging_promotion_loop import StagingPromotionLoop
from state import StateTracker

RC_CI_ISSUE = 7001
ESCALATION_ISSUE = 8002


@pytest.fixture(autouse=True)
def _offline_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the CH-4 evidence compiler and gh reconcile sweep off the network."""
    monkeypatch.setattr(
        evidence_pack,
        "compile_evidence_pack",
        AsyncMock(return_value=MagicMock(gap_count=0)),
    )

    async def _empty_list(*cmd: str, **_kwargs: object) -> str:
        assert cmd[:3] == ("gh", "pr", "list"), cmd
        return "[]"

    monkeypatch.setattr(subprocess_util, "run_subprocess", _empty_list)


def _make_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[StagingPromotionLoop, MagicMock, StateTracker]:
    monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
    monkeypatch.setenv("HYDRAFLOW_RC_CONSECUTIVE_FAILURE_ESCALATION_THRESHOLD", "2")
    cfg = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )

    async def _sleep(_s: float) -> None:
        return None

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )

    prs = MagicMock()
    prs.find_open_promotion_pr = AsyncMock(
        return_value=PRInfo(
            number=70,
            issue_number=0,
            branch="rc/2026-07-18-0400",
            url="https://github.com/o/r/pull/70",
            draft=False,
        )
    )
    prs.wait_for_ci = AsyncMock(return_value=(False, "ci failed: scenario tests"))
    prs.merge_promotion_pr = AsyncMock(return_value=True)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    prs.update_issue_body = AsyncMock()
    prs.get_pr_head_sha = AsyncMock(return_value="somesha")
    prs.list_rc_branches = AsyncMock(return_value=[])
    prs.delete_branch = AsyncMock(return_value=True)

    async def _create_issue(title: str, body: str, labels: list[str]) -> int:
        if "rc-promotion-stuck" in labels:
            return ESCALATION_ISSUE
        return RC_CI_ISSUE

    prs.create_issue = AsyncMock(side_effect=_create_issue)

    state = StateTracker(state_file=tmp_path / "s.json")
    loop = StagingPromotionLoop(config=cfg, prs=prs, deps=deps, state=state)
    return loop, prs, state


def _escalation_creates(prs: MagicMock) -> list:
    out = []
    for call in prs.create_issue.await_args_list:
        labels = call.kwargs.get("labels") or (
            call.args[2] if len(call.args) > 2 else []
        )
        if "rc-promotion-stuck" in labels:
            out.append(call)
    return out


@pytest.mark.asyncio
async def test_green_promotion_auto_closes_streak_escalation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact #9867 shape: red, red (escalates), green → escalation closes."""
    loop, prs, state = _make_loop(tmp_path, monkeypatch)

    await loop._do_work()  # red 1
    await loop._do_work()  # red 2 → escalation filed at threshold

    assert len(_escalation_creates(prs)) == 1
    tracked = state.get_rollup_issue("staging_promotion:rc_promotion_stuck")
    assert tracked is not None
    assert tracked["issue_number"] == ESCALATION_ISSUE

    prs.wait_for_ci.return_value = (True, "ok")
    result = await loop._do_work()  # green → auto-close

    assert result["status"] == "promoted"
    prs.close_issue.assert_any_await(ESCALATION_ISSUE)
    assert state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is None
    assert state.get_consecutive_rc_failures() == 0


@pytest.mark.asyncio
async def test_next_streak_escalates_fresh_after_auto_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dead-letter must not linger: a second stall files a NEW escalation."""
    loop, prs, _state = _make_loop(tmp_path, monkeypatch)

    await loop._do_work()  # red 1
    await loop._do_work()  # red 2 → escalation
    prs.wait_for_ci.return_value = (True, "ok")
    await loop._do_work()  # green → close + clear

    prs.wait_for_ci.return_value = (False, "ci failed: scenario tests")
    await loop._do_work()  # red 1 of streak 2
    await loop._do_work()  # red 2 of streak 2 → fresh escalation

    assert len(_escalation_creates(prs)) == 2
