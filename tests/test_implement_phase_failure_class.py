"""ImplementPhase counts failed builds by failure class (#11593 seam 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import TaskFactory, WorkerResultFactory
from tests.helpers import ConfigFactory, make_implement_phase

ISSUE = 42


def _config(tmp_path: Path):
    return ConfigFactory.create(
        max_issue_attempts=1,
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


def _agent(*, success: bool, error: str | None):
    async def agent(issue, wt_path, branch, **_kwargs):
        return WorkerResultFactory.create(
            issue_number=issue.id,
            branch=branch,
            success=success,
            error=error,
            commits=1,
            workspace_path=str(wt_path),
            transcript="t",
        )

    return agent


@pytest.mark.asyncio
async def test_failed_build_increments_its_failure_class(tmp_path: Path) -> None:
    phase, _, _ = make_implement_phase(
        _config(tmp_path),
        [TaskFactory.create(id=ISSUE)],
        agent_run=_agent(success=False, error="test-adequacy failed: missing tests"),
    )

    await phase.run_batch()

    counters = phase._state.get_session_counters()
    assert counters.implement_failures == {"test_adequacy": 1}


@pytest.mark.asyncio
async def test_successful_build_records_no_failure_class(tmp_path: Path) -> None:
    phase, _, _ = make_implement_phase(
        _config(tmp_path),
        [TaskFactory.create(id=ISSUE)],
        agent_run=_agent(success=True, error=None),
    )

    await phase.run_batch()

    assert phase._state.get_session_counters().implement_failures == {}
