"""Unit tests for PlanRetrySelfSolver — decompose then diagnose (#10735).

#11480 adds a third terminal verdict, ``already-satisfied``: the fix landed
(or is in flight), so the self-solver must neither diagnose nor exhaust.

The ADR-0105 decompose terminal itself is exercised end-to-end in
tests/scenarios/test_decompose_to_converge_scenario.py; here we pin the
self-solver's ladder logic by scripting ``decompose_or_escalate``'s verdict.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import giveup_self_solve
from config import HydraFlowConfig
from giveup_self_solve import PlanRetrySelfSolver
from giveup_window import SelfSolveOutcome
from state import StateTracker


def _solver(
    tmp_path: Path, *, prs: AsyncMock, diagnose_label: str = "hydraflow-diagnose"
) -> PlanRetrySelfSolver:
    return PlanRetrySelfSolver(
        config=HydraFlowConfig(),
        state=StateTracker(tmp_path / "state.json"),
        prs=prs,
        decomposer=object(),  # not reached — decompose_or_escalate is scripted
        council=object(),
        diagnose_label=diagnose_label,
    )


@pytest.mark.asyncio
async def test_decompose_success_returns_decomposed(
    tmp_path: Path, monkeypatch
) -> None:
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    async def _fake_decompose(**_kwargs: object) -> str:
        return "decomposed"

    monkeypatch.setattr(giveup_self_solve, "decompose_or_escalate", _fake_decompose)

    out = await _solver(tmp_path, prs=prs).solve(
        42, from_stage="ready", reason="thrash", issue_body="sprawling issue"
    )

    assert out is SelfSolveOutcome.DECOMPOSED
    # Decompose superseded the issue; no diagnose relabel needed.
    prs.swap_pipeline_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_decline_falls_back_to_diagnose(tmp_path: Path, monkeypatch) -> None:
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    async def _fake_decompose(**_kwargs: object) -> str:
        return "human-required"  # council declined / not wired / depth-capped

    monkeypatch.setattr(giveup_self_solve, "decompose_or_escalate", _fake_decompose)

    out = await _solver(tmp_path, prs=prs).solve(42, from_stage="ready", reason="x")

    assert out is SelfSolveOutcome.DIAGNOSED
    prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-diagnose")


@pytest.mark.asyncio
async def test_decline_with_no_diagnose_label_is_exhausted(
    tmp_path: Path, monkeypatch
) -> None:
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    async def _fake_decompose(**_kwargs: object) -> str:
        return "human-required"

    monkeypatch.setattr(giveup_self_solve, "decompose_or_escalate", _fake_decompose)

    out = await _solver(tmp_path, prs=prs, diagnose_label="").solve(
        42, from_stage="ready", reason="x"
    )

    assert out is SelfSolveOutcome.EXHAUSTED
    prs.swap_pipeline_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_diagnose_swap_failure_is_exhausted(tmp_path: Path, monkeypatch) -> None:
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock(side_effect=RuntimeError("gh down"))

    async def _fake_decompose(**_kwargs: object) -> str:
        return "human-required"

    monkeypatch.setattr(giveup_self_solve, "decompose_or_escalate", _fake_decompose)

    out = await _solver(tmp_path, prs=prs).solve(42, from_stage="ready", reason="x")

    assert out is SelfSolveOutcome.EXHAUSTED


@pytest.mark.asyncio
async def test_decompose_raise_falls_back_to_diagnose(
    tmp_path: Path, monkeypatch
) -> None:
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    async def _fake_decompose(**_kwargs: object) -> str:
        raise RuntimeError("council transport error")

    monkeypatch.setattr(giveup_self_solve, "decompose_or_escalate", _fake_decompose)

    out = await _solver(tmp_path, prs=prs).solve(42, from_stage="ready", reason="x")

    # A non-credit, non-bug decompose failure degrades to diagnose, not a crash.
    assert out is SelfSolveOutcome.DIAGNOSED


@pytest.mark.asyncio
@pytest.mark.parametrize("diagnose_label", ["hydraflow-diagnose", ""])
async def test_already_satisfied_skips_diagnose_and_human(
    tmp_path: Path, monkeypatch, diagnose_label: str
) -> None:
    """#11480: a fix that already landed is neither re-sliced nor diagnosed.

    ``decompose_or_escalate``'s third verdict must surface as its own
    ``SelfSolveOutcome``. Falling into the diagnose fallback would relabel an
    issue whose PR is about to close it; with no diagnose label wired it would
    read as EXHAUSTED and page a human for finished work.
    """
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    async def _fake_decompose(**_kwargs: object) -> str:
        return "already-satisfied"

    monkeypatch.setattr(giveup_self_solve, "decompose_or_escalate", _fake_decompose)

    out = await _solver(tmp_path, prs=prs, diagnose_label=diagnose_label).solve(
        42, from_stage="ready", reason="x"
    )

    assert out is SelfSolveOutcome.ALREADY_SATISFIED
    # No diagnose relabel: the issue stays in the pipeline and closes with its fix.
    prs.swap_pipeline_labels.assert_not_awaited()
