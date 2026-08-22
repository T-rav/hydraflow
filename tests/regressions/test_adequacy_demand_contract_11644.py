"""#11644 — the demand contract must never weaken the gate.

#11643's calibration found the test-adequacy gate is measurably *leaky* on the
only arm that can be scored (4 of 10 aged, gate-passed, merged PRs later
escaped), so the fix was the demand's shape, not the bar. These are the routes
by which "judge the retry against the pinned demand" could quietly become
"waive the rejection". The first implementation of the contract tripped the
empty-findings one: a ``RETRY`` whose ``GAPS:`` block was empty partitioned to
an empty blocking set and flipped itself to a pass.
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
_UNANCHORED_RETRY = (
    "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: boundary-condition gap in truncation logic\n"
)


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
@pytest.mark.parametrize(
    ("transcript", "uncovered", "pinned"),
    [
        pytest.param(
            "TEST_ADEQUACY_RESULT: OK",
            ["a.py:3"],
            _PIN,
            id="deterministic-coverage-gap-survives-the-pin",
        ),
        pytest.param(
            _UNANCHORED_RETRY,
            ["a.py:3"],
            _PIN,
            id="a-flipped-finder-verdict-still-faces-the-coverage-delta",
        ),
        pytest.param(
            "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY:   \n",
            [],
            _PIN,
            id="a-failing-verdict-that-states-nothing-still-rejects",
        ),
        pytest.param(
            "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: missing-error-path-coverage\n",
            [],
            [],
            id="a-first-attempt-is-never-waived",
        ),
    ],
)
async def test_the_contract_never_waives_a_rejection_it_must_not(
    config,
    event_bus: EventBus,
    agent_task,
    tmp_path: Path,
    transcript: str,
    uncovered: list[str],
    pinned: list[str],
) -> None:
    runner = _runner(config, event_bus)
    p = _patches(runner, AsyncMock(return_value=transcript), uncovered)
    with p[0], p[1], p[2], p[3]:
        result = await runner._run_skill(
            TEST_ADEQUACY,
            agent_task,
            tmp_path,
            "branch",
            worker_id=0,
            pinned_findings=pinned,
        )
    assert result.passed is False


@pytest.mark.asyncio
async def test_a_fail_closed_degraded_verifier_is_not_absorbed_by_the_pin(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """#9546's fail-closed default rejects a DEGRADED verifier run with a
    fabricated summary and no gaps. Recovering findings from that sentence
    (as the finder arm legitimately does) let the contract classify it as a
    new, unanchored demand and waive the very rejection the default exists to
    make. The override arm is judged on its ENUMERATED gaps only.
    """
    runner = _runner(config, event_bus)
    config.test_adequacy_verifier_enabled = True
    config.test_adequacy_verifier_fail_closed = True
    # Finder says OK (triggers the verifier); the verifier returns nothing.
    execute = AsyncMock(side_effect=["TEST_ADEQUACY_RESULT: OK", ""])
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
async def test_a_waived_retry_says_why_it_cleared_the_gate(
    config, event_bus: EventBus, agent_task, tmp_path: Path
) -> None:
    """A manifest must never read a contract flip as a plain adequacy OK."""
    runner = _runner(config, event_bus)
    p = _patches(runner, AsyncMock(return_value=_UNANCHORED_RETRY), [])
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
