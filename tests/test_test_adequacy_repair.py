"""Repair-in-run for the test-adequacy gate (#11593 seams 1 + 3).

Unit tests for the bounded repair loop's decision logic: a failing verdict's
concrete findings feed a focused repair prompt back to the implementer
worktree, the FULL check (coverage delta + independent verifier) re-runs, a
no-op repair burns its pass, the 0-disables invariants hold, the rejection
error string stays grep-compatible, and every rejection carries the
calibration telemetry record.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent import AgentRunner
from events import EventBus
from models import Task
from skill_registry import BUILTIN_SKILLS
from test_adequacy import build_test_adequacy_repair_prompt

TEST_ADEQUACY = next(s for s in BUILTIN_SKILLS if s.name == "test-adequacy")
DIFF_SANITY = next(s for s in BUILTIN_SKILLS if s.name == "diff-sanity")

_FINDER_RETRY = (
    "TEST_ADEQUACY_RESULT: RETRY\n"
    "SUMMARY: missing tests\n"
    "GAPS:\n"
    "- src/foo.py:bar — no test\n"
)
_FINDER_RETRY_SECOND = (
    "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: still missing edge cases\n"
)
_FINDER_OK = "TEST_ADEQUACY_RESULT: OK\nSUMMARY: adequate"
_VERIFIER_OVERRIDE = (
    "TEST_ADEQUACY_VERIFIER_RESULT: OVERRIDE\n"
    "SUMMARY: untested error path\n"
    "GAPS:\n"
    "- src/foo.py:bar — no test for the raise branch\n"
)


@pytest.fixture
def agent_task() -> Task:
    return Task(
        id=42,
        title="Fix the frobnicator",
        body="The frobnicator is broken. Please fix it.",
        tags=["ready"],
        comments=[],
        source_url="https://github.com/test-org/test-repo/issues/42",
    )


def _runner(
    config, event_bus: EventBus, *, passes: int = 1, verifier: bool = False
) -> AgentRunner:
    config.max_test_adequacy_attempts = 1
    config.test_adequacy_repair_passes = passes
    config.test_adequacy_verifier_enabled = verifier
    return AgentRunner(config, event_bus)


def _gate_patches(runner: AgentRunner, execute: AsyncMock, *, heads=("a", "b")):
    """Standard seams: commits/diff/execute mocked, coverage clean, git HEAD
    moves across the repair pass (so a re-check runs), salvage commit a no-op.
    """
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
            return_value=[],
        ),
        patch.object(
            runner, "_git_head", new_callable=AsyncMock, side_effect=list(heads)
        ),
        patch.object(
            runner,
            "_force_commit_uncommitted",
            new_callable=AsyncMock,
            return_value=True,
        ),
    )


async def _run(runner: AgentRunner, agent_task: Task, tmp_path: Path):
    return await runner._run_skill(
        TEST_ADEQUACY, agent_task, tmp_path, "branch", worker_id=0
    )


# ---------------------------------------------------------------------------
# Repair prompt builder (pure)
# ---------------------------------------------------------------------------


class TestRepairPromptBuilder:
    def test_prompt_names_the_concrete_findings(self) -> None:
        prompt = build_test_adequacy_repair_prompt(
            issue_number=42,
            issue_title="Fix it",
            verdict_source="llm-fail",
            summary="missing tests",
            findings=["src/foo.py:bar — no test"],
            pass_number=1,
            max_passes=1,
        )
        assert "src/foo.py:bar — no test" in prompt
        assert "REPAIR pass (1 of 1)" in prompt

    def test_prompt_labels_coverage_delta_source(self) -> None:
        prompt = build_test_adequacy_repair_prompt(
            issue_number=42,
            issue_title="Fix it",
            verdict_source="coverage-delta",
            summary="Coverage delta: 1 uncovered changed line(s)",
            findings=["src/foo.py:3"],
            pass_number=1,
            max_passes=2,
        )
        assert "coverage delta" in prompt.lower()

    def test_prompt_caps_the_findings_list(self) -> None:
        findings = [f"src/foo.py:{n}" for n in range(40)]
        prompt = build_test_adequacy_repair_prompt(
            issue_number=42,
            issue_title="Fix it",
            verdict_source="coverage-delta",
            summary="Coverage delta: 40 uncovered changed line(s)",
            findings=findings,
            pass_number=1,
            max_passes=1,
        )
        assert "src/foo.py:29" in prompt
        assert "src/foo.py:30" not in prompt
        assert "(+ 10 more)" in prompt


# ---------------------------------------------------------------------------
# Repair budget resolution
# ---------------------------------------------------------------------------


class TestSkillRepairBudget:
    def test_zero_for_skills_without_a_repair_seam(self, config, event_bus) -> None:
        config.test_adequacy_repair_passes = 3
        runner = AgentRunner(config, event_bus)
        assert runner._skill_repair_budget(DIFF_SANITY) == 0

    def test_reads_the_live_config_field_for_test_adequacy(
        self, config, event_bus
    ) -> None:
        runner = AgentRunner(config, event_bus)
        config.test_adequacy_repair_passes = 2
        assert runner._skill_repair_budget(TEST_ADEQUACY) == 2


# ---------------------------------------------------------------------------
# Repair loop decision logic
# ---------------------------------------------------------------------------


class TestRepairLoop:
    @pytest.mark.asyncio
    async def test_repair_pass_rescues_a_failing_finder_verdict(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = _runner(config, event_bus)
        execute = AsyncMock(side_effect=[_FINDER_RETRY, "wrote tests", _FINDER_OK])
        p = _gate_patches(runner, execute)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is True
        assert result.test_adequacy is not None
        assert result.test_adequacy.repair_outcomes == ["verdict-flipped"]

    @pytest.mark.asyncio
    async def test_repair_prompt_carries_the_current_findings(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = _runner(config, event_bus)
        execute = AsyncMock(side_effect=[_FINDER_RETRY, "wrote tests", _FINDER_OK])
        p = _gate_patches(runner, execute)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            await _run(runner, agent_task, tmp_path)
        repair_prompt = execute.await_args_list[1].args[1]
        assert "src/foo.py:bar — no test" in repair_prompt
        assert "REPAIR pass (1 of 1)" in repair_prompt

    @pytest.mark.asyncio
    async def test_noop_repair_burns_the_pass_without_a_recheck(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """A pass that moves nothing must not spend a re-check dispatch."""
        runner = _runner(config, event_bus)
        execute = AsyncMock(side_effect=[_FINDER_RETRY, "did nothing"])
        p = _gate_patches(runner, execute, heads=("same", "same"))
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is False
        assert execute.await_count == 2
        assert result.test_adequacy.repair_outcomes == ["no-change"]

    @pytest.mark.asyncio
    async def test_noop_repair_keeps_the_original_rejection_summary(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = _runner(config, event_bus)
        execute = AsyncMock(side_effect=[_FINDER_RETRY, "did nothing"])
        p = _gate_patches(runner, execute, heads=("same", "same"))
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            result = await _run(runner, agent_task, tmp_path)
        assert result.summary == "missing tests"

    @pytest.mark.asyncio
    async def test_vanished_diff_on_recheck_keeps_the_failing_verdict(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """A repair pass that empties the diff must not wash the gate out."""
        runner = _runner(config, event_bus)
        execute = AsyncMock(side_effect=[_FINDER_RETRY, "deleted everything"])
        p = _gate_patches(runner, execute)
        with (
            p[0],
            p[2],
            p[3],
            p[4],
            p[5],
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                side_effect=["+def foo(): pass\n", ""],
            ),
        ):
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is False
        assert result.summary == "missing tests"
        assert result.test_adequacy.repair_outcomes == ["no-change"]

    @pytest.mark.asyncio
    async def test_still_failing_recheck_rejects_with_the_final_verdict(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = _runner(config, event_bus)
        execute = AsyncMock(side_effect=[_FINDER_RETRY, "tried", _FINDER_RETRY_SECOND])
        p = _gate_patches(runner, execute)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is False
        assert "still missing edge cases" in result.summary
        assert result.test_adequacy.repair_outcomes == ["still-failing"]

    @pytest.mark.asyncio
    async def test_zero_repair_passes_goes_straight_to_rejection(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """test_adequacy_repair_passes=0 restores the pre-#11593 behavior."""
        runner = _runner(config, event_bus, passes=0)
        execute = AsyncMock(return_value=_FINDER_RETRY)
        repair_spy = AsyncMock(return_value=True)
        p = _gate_patches(runner, execute)
        with (
            p[0],
            p[1],
            p[2],
            p[3],
            patch.object(runner, "_run_skill_repair_pass", repair_spy),
        ):
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is False
        assert repair_spy.await_count == 0

    @pytest.mark.asyncio
    async def test_gate_kill_switch_disables_repair_too(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """max_test_adequacy_attempts=0 bypasses everything, repair included."""
        config.max_test_adequacy_attempts = 0
        config.test_adequacy_repair_passes = 3
        runner = AgentRunner(config, event_bus)
        execute = AsyncMock()
        with patch.object(runner, "_execute", execute):
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is True
        assert "disabled" in result.summary
        assert execute.await_count == 0

    @pytest.mark.asyncio
    async def test_repair_is_bounded_by_the_configured_budget(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = _runner(config, event_bus, passes=2)
        execute = AsyncMock(return_value=_FINDER_RETRY)
        repair_spy = AsyncMock(return_value=True)
        p = _gate_patches(runner, execute)
        with (
            p[0],
            p[1],
            p[2],
            p[3],
            patch.object(runner, "_run_skill_repair_pass", repair_spy),
        ):
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is False
        assert repair_spy.await_count == 2

    @pytest.mark.asyncio
    async def test_coverage_gaps_still_override_llm_ok_after_repair(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """Deterministic coverage findings beat an LLM OK on the re-check too."""
        runner = _runner(config, event_bus)
        execute = AsyncMock(return_value=_FINDER_OK)
        coverage = AsyncMock(return_value=["src/foo.py:3"])
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+def foo(): pass\n",
            ),
            patch.object(runner, "_execute", execute),
            patch.object(runner, "_run_coverage_delta_check", coverage),
            patch.object(
                runner,
                "_run_skill_repair_pass",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is False
        assert result.test_adequacy.verdict_source == "coverage-delta"
        assert result.test_adequacy.repair_outcomes == ["still-failing"]

    @pytest.mark.asyncio
    async def test_verifier_reruns_on_the_recheck_and_can_still_reject(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """The final verdict is the verifier-checked one, not the repair's claim."""
        runner = _runner(config, event_bus, verifier=True)
        execute = AsyncMock(side_effect=[_FINDER_RETRY, _FINDER_OK, _VERIFIER_OVERRIDE])
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
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
                return_value=[],
            ),
            patch.object(
                runner,
                "_run_skill_repair_pass",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is False
        assert result.test_adequacy.verdict_source == "verifier-override"
        assert "raise branch" in result.test_adequacy.findings[0]

    @pytest.mark.asyncio
    async def test_non_repair_skills_never_dispatch_a_repair_pass(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        config.max_diff_sanity_attempts = 1
        config.test_adequacy_repair_passes = 3
        runner = AgentRunner(config, event_bus)
        execute = AsyncMock(return_value="DIFF_SANITY_RESULT: RETRY\nSUMMARY: debug")
        repair_spy = AsyncMock(return_value=True)
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+import os\n",
            ),
            patch.object(runner, "_execute", execute),
            patch.object(runner, "_run_skill_repair_pass", repair_spy),
        ):
            result = await runner._run_skill(
                DIFF_SANITY, agent_task, tmp_path, "branch", worker_id=0
            )
        assert result.passed is False
        assert repair_spy.await_count == 0


# ---------------------------------------------------------------------------
# Rejection telemetry (#11593 seam 3)
# ---------------------------------------------------------------------------


class TestRejectionTelemetry:
    @pytest.mark.asyncio
    async def test_llm_fail_rejection_names_source_and_findings(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = _runner(config, event_bus, passes=0)
        execute = AsyncMock(return_value=_FINDER_RETRY)
        p = _gate_patches(runner, execute)
        with p[0], p[1], p[2], p[3]:
            result = await _run(runner, agent_task, tmp_path)
        assert result.test_adequacy.verdict_source == "llm-fail"
        assert result.test_adequacy.findings == ["src/foo.py:bar — no test"]
        assert result.test_adequacy.repair_passes_used == 0

    @pytest.mark.asyncio
    async def test_clean_first_pass_carries_no_telemetry_record(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = _runner(config, event_bus)
        execute = AsyncMock(return_value="agent chatter, no marker")
        p = _gate_patches(runner, execute)
        with p[0], p[1], p[2], p[3]:
            result = await _run(runner, agent_task, tmp_path)
        assert result.passed is True
        assert result.test_adequacy is None

    @pytest.mark.asyncio
    async def test_rescued_pass_records_the_repair_but_no_failing_source(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        runner = _runner(config, event_bus)
        execute = AsyncMock(side_effect=[_FINDER_RETRY, "wrote tests", _FINDER_OK])
        p = _gate_patches(runner, execute)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            result = await _run(runner, agent_task, tmp_path)
        assert result.test_adequacy.passed is True
        assert result.test_adequacy.verdict_source is None
        assert result.test_adequacy.repair_passes_used == 1


# ---------------------------------------------------------------------------
# Pinned demand across retries (#11644)
# ---------------------------------------------------------------------------

#: A retry finding that shares no substantive vocabulary with the pin below and
#: names nothing locatable — the 0.04-overlap pathology #11643 measured.
_FINDER_RETRY_NEW_UNANCHORED = (
    "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: boundary-condition gap in truncation logic\n"
)
#: A retry finding that is new but points at a file — a bar the retry can meet.
_FINDER_RETRY_NEW_ANCHORED = (
    "TEST_ADEQUACY_RESULT: RETRY\n"
    "SUMMARY: untested wiring\n"
    "GAPS:\n"
    "- src/widget.py:spin — no test for the boot path\n"
)
#: One anchored finding the pin never mentioned, plus one unlocatable one.
_MIXED_RETRY = (
    "TEST_ADEQUACY_RESULT: RETRY\n"
    "SUMMARY: gaps\n"
    "GAPS:\n"
    "- src/widget.py:spin — no test for the boot path\n"
    "- boundary-condition gap in truncation logic\n"
)
_PIN = ["src/frobnicator.py:rebuild_index — no test for the failure branch"]


class TestPinnedDemand:
    """The demand contract at the gate seam (#11644)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("transcript", "pinned", "pin_on", "expected_pass"),
        [
            pytest.param(
                _FINDER_RETRY_NEW_UNANCHORED,
                _PIN,
                True,
                True,
                id="new-unanchored-demand-cannot-reject-a-pinned-retry",
            ),
            pytest.param(
                _FINDER_RETRY_NEW_ANCHORED,
                _PIN,
                True,
                False,
                id="new-anchored-demand-still-rejects",
            ),
            pytest.param(
                _FINDER_RETRY,
                _PIN,
                True,
                False,
                id="restated-pinned-demand-still-rejects",
            ),
            pytest.param(
                _FINDER_RETRY_NEW_UNANCHORED,
                _PIN,
                False,
                False,
                id="kill-switch-restores-pre-11644-rejection",
            ),
            pytest.param(
                _FINDER_RETRY_NEW_UNANCHORED,
                [],
                True,
                False,
                id="first-attempt-without-a-pin-still-rejects",
            ),
            pytest.param(
                "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY:  \n",
                _PIN,
                True,
                False,
                id="verdict-stating-nothing-at-all-still-rejects",
            ),
            pytest.param(
                "TEST_ADEQUACY_RESULT: RETRY\n"
                "SUMMARY: src/frobnicator.py:rebuild_index still has no failure test\n",
                _PIN,
                True,
                False,
                id="summary-only-verdict-is-judged-on-its-summary",
            ),
        ],
    )
    async def test_the_contract_decides_whether_a_retry_is_rejected(
        self,
        config,
        event_bus: EventBus,
        agent_task,
        tmp_path: Path,
        transcript: str,
        pinned: list[str],
        pin_on: bool,
        expected_pass: bool,
    ) -> None:
        runner = _runner(config, event_bus, passes=0)
        runner._config.test_adequacy_pin_demand = pin_on
        p = _gate_patches(runner, AsyncMock(return_value=transcript))
        with p[0], p[1], p[2], p[3]:
            result = await runner._run_skill(
                TEST_ADEQUACY,
                agent_task,
                tmp_path,
                "branch",
                worker_id=0,
                pinned_findings=pinned,
            )
        assert result.passed is expected_pass

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("transcript", "field", "expected"),
        [
            pytest.param(
                _FINDER_RETRY_NEW_UNANCHORED,
                "advisory_findings",
                ["boundary-condition gap in truncation logic"],
                id="absorbed-demand-recorded-as-advisory",
            ),
            pytest.param(
                _FINDER_RETRY_NEW_UNANCHORED,
                "pinned_findings",
                _PIN,
                id="pin-in-force-echoed-into-the-telemetry",
            ),
            pytest.param(
                _FINDER_RETRY_NEW_ANCHORED,
                "new_findings",
                ["src/widget.py:spin — no test for the boot path"],
                id="new-anchored-demand-recorded-as-new",
            ),
        ],
    )
    async def test_the_contract_is_recorded_in_the_telemetry(
        self,
        config,
        event_bus: EventBus,
        agent_task,
        tmp_path: Path,
        transcript: str,
        field: str,
        expected: list[str],
    ) -> None:
        """The moving bar stays measurable — the fix must not hide what it absorbs."""
        runner = _runner(config, event_bus, passes=0)
        p = _gate_patches(runner, AsyncMock(return_value=transcript))
        with p[0], p[1], p[2], p[3]:
            result = await runner._run_skill(
                TEST_ADEQUACY,
                agent_task,
                tmp_path,
                "branch",
                worker_id=0,
                pinned_findings=_PIN,
            )
        assert getattr(result.test_adequacy, field) == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("section", "expected"),
        [
            pytest.param(
                0,
                "src/widget.py:spin — no test for the boot path",
                id="blocking-finding-is-what-the-pass-must-close",
            ),
            pytest.param(
                -1,
                "boundary-condition gap in truncation logic",
                id="absorbed-finding-is-marked-advisory",
            ),
        ],
    )
    async def test_the_repair_prompt_separates_blocking_from_advisory(
        self,
        config,
        event_bus: EventBus,
        agent_task,
        tmp_path: Path,
        section: int,
        expected: str,
    ) -> None:
        """Seam 1's prompt asks for what the run must close, not the advisory noise."""
        runner = _runner(config, event_bus, passes=1)
        execute = AsyncMock(side_effect=[_MIXED_RETRY, "wrote tests", _FINDER_OK])
        p = _gate_patches(runner, execute)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            await runner._run_skill(
                TEST_ADEQUACY,
                agent_task,
                tmp_path,
                "branch",
                worker_id=0,
                pinned_findings=_PIN,
            )
        prompt = execute.call_args_list[1].args[1].split("## Advisory")[section]
        assert expected in prompt

    @pytest.mark.asyncio
    async def test_a_pin_is_only_applied_to_the_skill_that_declares_one(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """diff-sanity has no pin seam: its findings are unaffected."""
        runner = _runner(config, event_bus, passes=0)
        config.max_diff_sanity_attempts = 1
        execute = AsyncMock(
            return_value="DIFF_SANITY_RESULT: RETRY\nSUMMARY: unlocatable prose\n"
        )
        p = _gate_patches(runner, execute)
        with p[0], p[1], p[2], p[3]:
            result = await runner._run_skill(
                DIFF_SANITY,
                agent_task,
                tmp_path,
                "branch",
                worker_id=0,
                pinned_findings=_PIN,
            )
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_a_deterministic_coverage_gap_is_never_waived_by_the_pin(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """The #11603 invariant survives: coverage gaps override an LLM OK."""
        runner = _runner(config, event_bus, passes=0)
        p = _gate_patches(runner, AsyncMock(return_value=_FINDER_OK))
        with (
            p[0],
            p[1],
            p[2],
            patch.object(
                runner,
                "_run_coverage_delta_check",
                new_callable=AsyncMock,
                return_value=["src/quux.py:17"],
            ),
        ):
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
    async def test_a_verifier_override_of_a_new_unanchored_gap_does_not_reject(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """The override arm routes through the same contract as the finder."""
        runner = _runner(config, event_bus, passes=0, verifier=True)
        execute = AsyncMock(
            side_effect=[
                _FINDER_OK,
                "TEST_ADEQUACY_VERIFIER_RESULT: OVERRIDE\n"
                "SUMMARY: boundary-condition gap in truncation logic\n",
            ]
        )
        p = _gate_patches(runner, execute)
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


# ---------------------------------------------------------------------------
# run() integration: error-string compatibility + WorkerResult propagation
# ---------------------------------------------------------------------------


class TestRunPropagation:
    @pytest.mark.asyncio
    async def test_run_keeps_the_rejection_error_format_and_telemetry(
        self, config, event_bus: EventBus, agent_task, tmp_path: Path
    ) -> None:
        """Downstream tooling greps `test-adequacy failed:` — the format is API."""
        config.max_test_adequacy_attempts = 1
        config.test_adequacy_repair_passes = 0
        config.test_adequacy_verifier_enabled = False
        runner = AgentRunner(config, event_bus)

        async def fake_execute(cmd, prompt, *args, **kwargs) -> str:
            if "Test Adequacy skill" in prompt:
                return _FINDER_RETRY
            return "DIFF_SANITY_RESULT: OK\nSCOPE_CHECK_RESULT: OK\nSUMMARY: ok"

        with (
            patch.object(runner, "_execute", AsyncMock(side_effect=fake_execute)),
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+def foo(): pass\n",
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is False
        assert result.error == "test-adequacy failed: missing tests"
        assert result.test_adequacy is not None
