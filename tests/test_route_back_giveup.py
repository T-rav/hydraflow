"""RouteBackCoordinator give-up window mode → self-solve, not human (#10735).

Proves the corrected escalation ladder at the coordinator seam:
  * count < N within T → ROUTED (convergent retry untouched);
  * N-in-T exhausted + self-solve decomposes/diagnoses → SELF_SOLVED, NO human;
  * N-in-T exhausted + the fix already landed (#11480) → SELF_SOLVED, no relabel
    at all — the issue stays in the pipeline and closes with its fix;
  * self-solve exhausted → human-required (ESCALATED), logged as a break;
  * reset_window (called on convergence) clears the window.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from giveup_window import GiveUpClass, GiveUpTracker, GiveUpWindow, SelfSolveOutcome
from issue_cache import IssueCache
from mockworld.fakes.fake_route_back_counter import FakeRouteBackCounter
from route_back import RouteBackCoordinator, RouteBackOutcome
from state import StateTracker


class _FakeSelfSolve:
    """A SelfSolver that returns a scripted outcome and records its calls."""

    def __init__(self, outcome: SelfSolveOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[int, str, str]] = []

    async def solve(
        self, issue_id: int, *, from_stage: str, reason: str, issue_body: str = ""
    ) -> SelfSolveOutcome:
        self.calls.append((issue_id, from_stage, issue_body))
        return self.outcome


def _coordinator(
    tmp_path: Path,
    *,
    self_solve: _FakeSelfSolve | None,
    n: int = 2,
    t: int = 3600,
) -> tuple[RouteBackCoordinator, AsyncMock, StateTracker]:
    cache = IssueCache(tmp_path / "cache", enabled=True)
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    state = StateTracker(tmp_path / "state.json")
    window = GiveUpWindow(GiveUpClass.PLAN_RETRY, max_restarts=n, window_seconds=t)
    coordinator = RouteBackCoordinator(
        cache=cache,
        prs=prs,
        counter=FakeRouteBackCounter(),
        hitl_label="human-required",
        diagnose_label="hydraflow-diagnose",
        max_route_backs=2,
        give_up_tracker=GiveUpTracker(state),
        plan_retry_window=window,
        self_solve=self_solve,
    )
    return coordinator, prs, state


async def _route(coordinator: RouteBackCoordinator, issue_id: int = 42):
    return await coordinator.route_back(
        issue_id,
        from_stage="ready",
        to_stage="plan",
        reason="review v3 has critical findings",
        issue_body="the frobnicator never converges",
    )


class TestGiveUpWindowActive:
    def test_window_supersedes_legacy_cap(self, tmp_path: Path) -> None:
        coordinator, _prs, _state = _coordinator(tmp_path, self_solve=None)
        assert coordinator.give_up_window_active is True


class TestUnderWindowRoutesBack:
    @pytest.mark.asyncio
    async def test_below_threshold_is_routed(self, tmp_path: Path) -> None:
        ss = _FakeSelfSolve(SelfSolveOutcome.DECOMPOSED)
        coordinator, prs, _state = _coordinator(tmp_path, self_solve=ss, n=3)

        result = await _route(coordinator)

        assert result.outcome == RouteBackOutcome.ROUTED
        assert result.counter == 1
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "plan")
        assert ss.calls == []  # self-solve not triggered yet


class TestExhaustedDecomposesNotHuman:
    @pytest.mark.asyncio
    async def test_decompose_self_solves_without_human(self, tmp_path: Path) -> None:
        ss = _FakeSelfSolve(SelfSolveOutcome.DECOMPOSED)
        coordinator, prs, state = _coordinator(tmp_path, self_solve=ss, n=2)

        first = await _route(coordinator)
        assert first.outcome == RouteBackOutcome.ROUTED

        second = await _route(coordinator)

        # The give-up window (N=2) is exhausted → self-solve, NOT human.
        assert second.outcome == RouteBackOutcome.SELF_SOLVED
        assert len(ss.calls) == 1
        assert ss.calls[0] == (42, "ready", "the frobnicator never converges")
        # human-required label must NEVER be applied on the decompose path.
        swapped_labels = [c.args[1] for c in prs.swap_pipeline_labels.await_args_list]
        assert "human-required" not in swapped_labels
        # Only the first (routed) cycle swapped to plan; the exhausted cycle did not.
        assert swapped_labels == ["plan"]
        # The self-solve action is recorded for the /api give-up surface.
        assert (
            state.get_give_up_snapshot(42)["plan_retry"]["last_action"] == "decompose"
        )

    @pytest.mark.asyncio
    async def test_diagnose_self_solves_without_human(self, tmp_path: Path) -> None:
        ss = _FakeSelfSolve(SelfSolveOutcome.DIAGNOSED)
        coordinator, prs, state = _coordinator(tmp_path, self_solve=ss, n=1)

        result = await _route(coordinator)

        assert result.outcome == RouteBackOutcome.SELF_SOLVED
        swapped_labels = [c.args[1] for c in prs.swap_pipeline_labels.await_args_list]
        assert "human-required" not in swapped_labels
        assert state.get_give_up_snapshot(42)["plan_retry"]["last_action"] == "diagnose"

    @pytest.mark.asyncio
    async def test_already_satisfied_self_solves_without_human(
        self, tmp_path: Path
    ) -> None:
        """#11480: the self-solver found the fix already landed. Nothing to
        route: no plan, no diagnose, and above all no human-required — the
        issue stays where it is and closes with its fix."""
        ss = _FakeSelfSolve(SelfSolveOutcome.ALREADY_SATISFIED)
        coordinator, prs, state = _coordinator(tmp_path, self_solve=ss, n=1)

        result = await _route(coordinator)

        assert result.outcome == RouteBackOutcome.SELF_SOLVED
        assert "already-satisfied" in result.reason
        prs.swap_pipeline_labels.assert_not_awaited()
        assert (
            state.get_give_up_snapshot(42)["plan_retry"]["last_action"]
            == "already-satisfied"
        )


class TestSelfSolveExhaustedGoesToHumanAsLastResort:
    @pytest.mark.asyncio
    async def test_exhausted_applies_human_required(
        self, tmp_path: Path, caplog
    ) -> None:
        ss = _FakeSelfSolve(SelfSolveOutcome.EXHAUSTED)
        coordinator, prs, state = _coordinator(tmp_path, self_solve=ss, n=1)

        with caplog.at_level(logging.WARNING, logger="hydraflow.route_back"):
            result = await _route(coordinator)

        assert result.outcome == RouteBackOutcome.ESCALATED
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "human-required")
        # Emitted only as a rare, logged break.
        assert any("BREAK" in rec.message for rec in caplog.records)
        assert (
            state.get_give_up_snapshot(42)["plan_retry"]["last_action"]
            == "human-required"
        )

    @pytest.mark.asyncio
    async def test_no_self_solver_falls_to_human(self, tmp_path: Path) -> None:
        coordinator, prs, _state = _coordinator(tmp_path, self_solve=None, n=1)

        result = await _route(coordinator)

        assert result.outcome == RouteBackOutcome.ESCALATED
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "human-required")


class TestConvergenceResetPreservesRetry:
    @pytest.mark.asyncio
    async def test_reset_window_lets_issue_retry_again(self, tmp_path: Path) -> None:
        ss = _FakeSelfSolve(SelfSolveOutcome.DECOMPOSED)
        coordinator, _prs, _state = _coordinator(tmp_path, self_solve=ss, n=2)

        # One route-back, then the issue converges (gate pass) → reset.
        await _route(coordinator)
        coordinator.reset_window(42)

        # A subsequent unrelated blocking cycle starts fresh, so it ROUTES
        # rather than immediately self-solving.
        result = await _route(coordinator)
        assert result.outcome == RouteBackOutcome.ROUTED
        assert ss.calls == []


class TestLegacyModeUnchanged:
    @pytest.mark.asyncio
    async def test_no_window_uses_monotonic_cap(self, tmp_path: Path) -> None:
        cache = IssueCache(tmp_path / "cache", enabled=True)
        prs = AsyncMock()
        prs.swap_pipeline_labels = AsyncMock()
        coordinator = RouteBackCoordinator(
            cache=cache,
            prs=prs,
            counter=FakeRouteBackCounter(),
            hitl_label="hydraflow-hitl",
            diagnose_label="hydraflow-diagnose",
            max_route_backs=2,
        )
        assert coordinator.give_up_window_active is False

        r1 = await _route(coordinator)
        r2 = await _route(coordinator)
        r3 = await _route(coordinator)

        assert r1.outcome == RouteBackOutcome.ROUTED
        assert r2.outcome == RouteBackOutcome.ROUTED
        # 3rd exceeds cap → legacy diagnose/HITL escalation (unchanged).
        assert r3.outcome == RouteBackOutcome.ESCALATED
