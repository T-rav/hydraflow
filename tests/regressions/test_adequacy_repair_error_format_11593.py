"""Regression pin for the #11593 repair-in-run rejection contract.

When every bounded repair pass is spent and the test-adequacy verdict still
fails, the run's error must keep the EXACT pre-#11593 manifest format —
``test-adequacy failed: <summary>`` — because downstream tooling (manifest
audits, prior_failure retry framing, failure-class counters) greps that
prefix. A repair pass that runs but does not flip the verdict must burn its
pass and change nothing about the rejection surface.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent import AgentRunner
from events import EventBus
from implement_failure_class import classify_implement_failure
from models import Task
from tests.helpers import ConfigFactory

_FINDER_RETRY = (
    "TEST_ADEQUACY_RESULT: RETRY\n"
    "SUMMARY: missing tests\n"
    "GAPS:\n"
    "- src/foo.py:bar — no test\n"
)


@pytest.mark.asyncio
async def test_rejection_after_repair_passes_preserves_manifest_error_format(
    tmp_path: Path,
) -> None:
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    config.max_test_adequacy_attempts = 1
    config.test_adequacy_repair_passes = 1
    config.test_adequacy_verifier_enabled = False
    runner = AgentRunner(config, EventBus())
    task = Task(
        id=42,
        title="Fix the frobnicator",
        body="broken",
        tags=["ready"],
        comments=[],
        source_url="https://github.com/test-org/test-repo/issues/42",
    )

    async def fake_execute(cmd, prompt, *args, **kwargs) -> str:
        if "Test Adequacy" in prompt:
            return _FINDER_RETRY
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
        patch.object(
            runner,
            "_run_coverage_delta_check",
            new_callable=AsyncMock,
            return_value=[],
        ),
        # The repair pass runs (HEAD moved) but the re-check still fails.
        patch.object(
            runner,
            "_run_skill_repair_pass",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.run(task, tmp_path, "agent/issue-42")

    assert result.success is False
    assert result.error == "test-adequacy failed: missing tests"


def test_rejection_error_format_still_classifies_as_test_adequacy() -> None:
    """The failure-class counter keys off the same grep prefix."""
    assert (
        classify_implement_failure("test-adequacy failed: missing tests")
        == "test_adequacy"
    )
