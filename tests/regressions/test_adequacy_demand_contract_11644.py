"""#11644 — the demand contract must never weaken the gate.

#11643's calibration found the test-adequacy gate is measurably *leaky* on the
only arm that can be scored (4 of 10 aged, gate-passed, merged PRs later
escaped), so the fix was the demand's shape, not the bar. These are the
invariants that keep it that way — each one is a route by which "judge the
retry against the pinned demand" could quietly become "waive the rejection",
and the first implementation of the contract tripped the second one.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent import AgentRunner
from events import EventBus
from models import Task
from skill_gate import PIN_CLOSED_SUMMARY
from skill_registry import BUILTIN_SKILLS

TEST_ADEQUACY = next(s for s in BUILTIN_SKILLS if s.name == "test-adequacy")

_PIN = ["src/frobnicator.py:rebuild_index — no test for the failure branch"]


@pytest.fixture
def agent_task() -> Task:
    return Task(
        id=11644,
        title="Anchor the adequacy demand",
        body="body",
        tags=["ready"],
        comments=[],
        source_url="https://github.com/test-org/test-repo/issues/11644",
    )


def _runner(config, event_bus: EventBus) -> AgentRunner:
    config.max_test_adequacy_attempts = 1
    config.test_adequacy_repair_passes = 0
    config.test_adequacy_verifier_enabled = False
    return AgentRunner(config, event_bus)


def _patches(runner: AgentRunner, execute: AsyncMock, uncovered: list[str]):
    return (
        patch.object(runner, "_count_commits", new_callable=AsyncMock, return_value=1),
        patch.object(
            runner,
            "_get_branch_diff",
            new_callable=AsyncMock,
            return_value="+def foo(): pass\n",
        ),
        patch.object(runner, "_execute", execute),
        patch.object(
            runner,
            "_run_coverage_delta_check",
            new_callable=AsyncMock,
            return_value=uncovered,
        ),
    )


@pytest.mark.asyncio
async def test_a_deterministic_coverage_gap_survives_the_pin(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """#11603's invariant: a coverage gap still overrides an LLM OK."""
    runner = _runner(config, event_bus)
    p = _patches(runner, AsyncMock(return_value="TEST_ADEQUACY_RESULT: OK"), ["a.py:3"])
    with p[0], p[1], p[2], p[3]:
        result = await runner._run_skill(
            TEST_ADEQUACY,
            agent_task,
            tmp_path,
            "branch",
            worker_id=0,
            pinned_findings=_PIN,
        )
    assert result.passed is False


@pytest.mark.asyncio
async def test_a_flipped_finder_verdict_still_faces_the_coverage_delta(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """The contract runs BEFORE the coverage check, never instead of it.

    Applying it at the end would let a pinned retry skip ``make coverage``
    entirely — a real weakening dressed as a bounded demand.
    """
    runner = _runner(config, event_bus)
    execute = AsyncMock(
        return_value=(
            "TEST_ADEQUACY_RESULT: RETRY\n"
            "SUMMARY: boundary-condition gap in truncation logic\n"
        )
    )
    p = _patches(runner, execute, ["a.py:3"])
    with p[0], p[1], p[2], p[3]:
        result = await runner._run_skill(
            TEST_ADEQUACY,
            agent_task,
            tmp_path,
            "branch",
            worker_id=0,
            pinned_findings=_PIN,
        )
    assert result.passed is False


@pytest.mark.asyncio
async def test_a_failing_verdict_that_states_nothing_still_rejects(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """Nothing stated ⇒ nothing shown closed. The first cut flipped this to pass."""
    runner = _runner(config, event_bus)
    execute = AsyncMock(return_value="TEST_ADEQUACY_RESULT: RETRY\nSUMMARY:   \n")
    p = _patches(runner, execute, [])
    with p[0], p[1], p[2], p[3]:
        result = await runner._run_skill(
            TEST_ADEQUACY,
            agent_task,
            tmp_path,
            "branch",
            worker_id=0,
            pinned_findings=_PIN,
        )
    assert result.passed is False


@pytest.mark.asyncio
async def test_a_first_attempt_is_never_waived(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """No pin ⇒ pre-#11644 strictness: every finding blocks, anchored or not."""
    runner = _runner(config, event_bus)
    execute = AsyncMock(
        return_value=(
            "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: missing-error-path-coverage\n"
        )
    )
    p = _patches(runner, execute, [])
    with p[0], p[1], p[2], p[3]:
        result = await runner._run_skill(
            TEST_ADEQUACY, agent_task, tmp_path, "branch", worker_id=0
        )
    assert result.passed is False


@pytest.mark.asyncio
async def test_the_gate_kill_switch_still_disables_everything(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """``max_test_adequacy_attempts=0`` disables the gate, contract included."""
    runner = _runner(config, event_bus)
    config.max_test_adequacy_attempts = 0
    execute = AsyncMock(return_value="TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: x\n")
    p = _patches(runner, execute, ["a.py:3"])
    with p[0], p[1], p[2], p[3]:
        result = await runner._run_skill(
            TEST_ADEQUACY,
            agent_task,
            tmp_path,
            "branch",
            worker_id=0,
            pinned_findings=_PIN,
        )
    assert result.passed is True


@pytest.mark.asyncio
async def test_the_rejection_error_format_is_unchanged(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """Downstream tooling greps ``test-adequacy failed:`` — the format is API."""
    runner = _runner(config, event_bus)

    async def fake_execute(cmd, prompt, *args, **kwargs) -> str:
        if "Test Adequacy skill" in prompt:
            return "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: missing tests\n"
        return "DIFF_SANITY_RESULT: OK\nSCOPE_CHECK_RESULT: OK\nSUMMARY: ok"

    with (
        patch.object(runner, "_execute", AsyncMock(side_effect=fake_execute)),
        patch.object(runner, "_count_commits", new_callable=AsyncMock, return_value=1),
        patch.object(
            runner,
            "_get_branch_diff",
            new_callable=AsyncMock,
            return_value="+def foo(): pass\n",
        ),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.run(
            agent_task, tmp_path, "agent/issue-11644", pinned_adequacy_findings=_PIN
        )

    assert result.error == "test-adequacy failed: missing tests"


@pytest.mark.asyncio
async def test_a_waived_retry_says_why_it_cleared_the_gate(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """A manifest must never read a contract flip as a plain adequacy OK."""
    runner = _runner(config, event_bus)
    execute = AsyncMock(
        return_value=(
            "TEST_ADEQUACY_RESULT: RETRY\n"
            "SUMMARY: boundary-condition gap in truncation logic\n"
        )
    )
    p = _patches(runner, execute, [])
    with p[0], p[1], p[2], p[3]:
        result = await runner._run_skill(
            TEST_ADEQUACY,
            agent_task,
            tmp_path,
            "branch",
            worker_id=0,
            pinned_findings=_PIN,
        )
    assert result.summary == PIN_CLOSED_SUMMARY
