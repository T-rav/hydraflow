"""Regression pins for #11568 — implement-seam attempt waste.

Measured 2026-08-21 (agent issues, per merged issue):

    attempts mean            1.21 → 2.22
    issues with ≥2 attempts  32 % → 71 %
    W5 spec review fired     29 % → 51 %
    created → closed median  3.9 h → 7.6 h

Of 153 implement results since 07-21, 13 hit the flat 3600s ``agent_timeout``
and 13 ended "No commits found on branch" — and every zero-commit attempt then
burned a second and third build on the same shape. Two rules now hold:

1. **The implement timeout is tiered by triage complexity** (the field
   #11304/#11305 already tier on), with ``agent_timeout`` as ceiling AND
   default-when-unknown. A spawn can only ever be shortened, never lengthened.
2. **The first zero-commit result routes to diagnose** (``implement_no_progress_
   abort_attempts`` default 1) with the transcript tail — no W5 reviewer spawn,
   no attempt 2 — while a credit-exhausted run still raises through untouched
   (ADR-0119). ``0`` restores the retry-to-cap shape for operators who want it.

If any regress, the factory goes back to spending ~2× the builds per merge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import HydraFlowConfig
from implement_timeout import IMPLEMENT_TIMEOUT_TIERS, tiered_implement_timeout
from subprocess_util import CreditExhaustedError
from tests.conftest import TaskFactory, WorkerResultFactory
from tests.helpers import ConfigFactory, make_implement_phase

ISSUE = 42


def _config(tmp_path: Path) -> HydraFlowConfig:
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


def _zero_commit_agent(calls: list[int]):
    async def agent(issue, wt_path, branch, **_kwargs):
        calls.append(issue.id)
        return WorkerResultFactory.create(
            issue_number=issue.id,
            branch=branch,
            success=False,
            error="No commits found on branch",
            commits=0,
            workspace_path=str(wt_path),
            transcript="…reasoning…TAIL",
        )

    return agent


# ---------------------------------------------------------------------------
# 1. Tiered timeout
# ---------------------------------------------------------------------------


def test_default_abort_threshold_is_the_first_zero_commit_result() -> None:
    assert HydraFlowConfig(repo="t/r").implement_no_progress_abort_attempts == 1


def test_tier_table_shape_is_pinned() -> None:
    """1–2 → ½, 3–4 → ¾, 5+ → ceiling (the table in the PR body)."""
    assert IMPLEMENT_TIMEOUT_TIERS == ((2, 0.5), (4, 0.75))


@pytest.mark.parametrize(
    ("complexity", "expected"),
    [(None, 3600), (0, 3600), (1, 1800), (2, 1800), (3, 2700), (4, 2700), (5, 3600), (10, 3600)],
)
def test_tier_values_at_the_default_ceiling(complexity, expected: int) -> None:
    assert tiered_implement_timeout(complexity, 3600) == expected


@pytest.mark.parametrize("complexity", [None, 0, 1, 3, 5, 10])
def test_tiering_never_lengthens_a_spawn(complexity) -> None:
    for ceiling in (60, 900, 3600, 14400):
        assert tiered_implement_timeout(complexity, ceiling) <= ceiling


# ---------------------------------------------------------------------------
# 2. Zero-commit abort
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_zero_commit_result_routes_to_diagnose_with_tail(
    tmp_path: Path,
) -> None:
    calls: list[int] = []
    phase, _, prs = make_implement_phase(
        _config(tmp_path), [TaskFactory.create(id=ISSUE)], agent_run=_zero_commit_agent(calls)
    )

    await phase.run_batch()

    prs.swap_pipeline_labels.assert_any_call(ISSUE, "hydraflow-diagnose")
    context = phase._state.get_escalation_context(ISSUE)
    assert context is not None and (context.agent_transcript or "").endswith("TAIL")
    assert calls == [ISSUE]


@pytest.mark.asyncio
async def test_zero_commit_abort_skips_the_spec_reviewer_spawn(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock

    reviewer = AsyncMock()
    phase, _, _ = make_implement_phase(
        _config(tmp_path),
        [TaskFactory.create(id=ISSUE)],
        agent_run=_zero_commit_agent([]),
        spec_reviewer=reviewer,
    )

    await phase.run_batch()

    reviewer.review.assert_not_awaited()


@pytest.mark.asyncio
async def test_credit_exhaustion_raises_through_and_is_not_routed(tmp_path: Path) -> None:
    async def capped(issue, wt_path, branch, **_kwargs):
        raise CreditExhaustedError("limit reached")

    phase, _, prs = make_implement_phase(
        _config(tmp_path), [TaskFactory.create(id=ISSUE)], agent_run=capped
    )

    with pytest.raises(CreditExhaustedError):
        await phase.run_batch()

    assert (ISSUE, "hydraflow-diagnose") not in [
        c.args for c in prs.swap_pipeline_labels.call_args_list
    ]


@pytest.mark.asyncio
async def test_threshold_zero_restores_the_retry_to_cap_shape(tmp_path: Path) -> None:
    config = _config(tmp_path).model_copy(
        update={"implement_no_progress_abort_attempts": 0}
    )
    phase, _, prs = make_implement_phase(
        config, [TaskFactory.create(id=ISSUE)], agent_run=_zero_commit_agent([])
    )

    await phase.run_batch()

    assert phase._state.get_hitl_cause(ISSUE) is None
    assert (ISSUE, "hydraflow-diagnose") not in [
        c.args for c in prs.swap_pipeline_labels.call_args_list
    ]
