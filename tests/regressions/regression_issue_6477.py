"""Regression test for issue #6477.

Bug: ``diagnostic_loop.DiagnosticLoop._process_issue()`` destroys the
workspace in a ``finally`` block (lines 236-245) regardless of whether
the fix succeeded.  When the fix succeeds, the workspace contains the
committed changes needed by the review phase.  Destroying it before the
review phase picks it up causes a zero-commit failure — the diagnostic
loop effectively never lands a fix.

Expected behaviour after fix:
  - When ``runner.fix()`` returns ``(True, ...)`` (success), the workspace
    is **not** destroyed — it is retained for the review phase.
  - When ``runner.fix()`` returns ``(False, ...)`` (failure) or raises,
    the workspace **is** destroyed (cleanup).

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from diagnostic_loop import DiagnosticLoop
from models import DiagnosisResult, EscalationContext, Severity
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_diagnosis(*, fixable: bool = True) -> DiagnosisResult:
    return DiagnosisResult(
        root_cause="test root cause",
        severity=Severity.P2_FUNCTIONAL,
        fixable=fixable,
        fix_plan="apply the fix",
        human_guidance="check the logs",
        affected_files=["src/foo.py"],
    )


def _make_context() -> EscalationContext:
    return EscalationContext(cause="ci_failure", origin_phase="review")


def _make_loop_with_workspaces(
    tmp_path: Path,
) -> tuple[DiagnosticLoop, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build a DiagnosticLoop with a workspace manager mock.

    Returns (loop, runner, prs, state, workspaces).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    runner = MagicMock()
    runner.diagnose = AsyncMock(return_value=_make_diagnosis())
    runner.fix = AsyncMock(return_value=(True, "fixed successfully"))

    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.post_comment = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=_make_context())
    state.get_diagnostic_attempts = MagicMock(return_value=[])
    state.add_diagnostic_attempt = MagicMock()
    state.set_diagnosis_severity = MagicMock()

    workspaces = MagicMock()
    wt_path = deps.config.workspace_path_for_issue(42)
    workspaces.create = AsyncMock(return_value=wt_path)
    workspaces.destroy = AsyncMock()

    loop = DiagnosticLoop(
        config=deps.config,
        runner=runner,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
        workspaces=workspaces,
    )
    return loop, runner, prs, state, workspaces


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkspaceNotDestroyedOnSuccess:
    """When diagnostic fix succeeds, workspace must be retained for review."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6477 — fix not yet landed", strict=False)
    async def test_workspace_not_destroyed_on_successful_fix(
        self, tmp_path: Path
    ) -> None:
        """BUG (current): the ``finally`` block at line 236 unconditionally
        calls ``workspaces.destroy(issue_number)`` — even when the fix
        succeeded.  The review phase then finds no worktree and fails with
        a zero-commit error.

        CORRECT: ``destroy`` must NOT be called when the fix succeeds.
        """
        loop, runner, _prs, _state, workspaces = _make_loop_with_workspaces(tmp_path)
        runner.fix.return_value = (True, "fixed successfully")

        # Ensure the workspace path exists so the create branch is skipped
        wt_path = loop._config.workspace_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        outcome = await loop._process_issue(42, "Bug title", "Bug body")

        assert outcome == "fixed"
        workspaces.destroy.assert_not_awaited()


class TestWorkspaceDestroyedOnFailure:
    """When diagnostic fix fails, workspace must still be cleaned up."""

    @pytest.mark.asyncio
    async def test_workspace_destroyed_on_failed_fix(self, tmp_path: Path) -> None:
        """On fix failure the workspace should be destroyed — this is the
        correct cleanup path that must continue to work.
        """
        loop, runner, _prs, state, workspaces = _make_loop_with_workspaces(tmp_path)
        runner.fix.return_value = (False, "could not fix")
        # Ensure attempts_after < max so we get "retry" not "escalated"
        state.get_diagnostic_attempts.return_value = []

        wt_path = loop._config.workspace_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        outcome = await loop._process_issue(42, "Bug title", "Bug body")

        assert outcome == "retry"
        workspaces.destroy.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_workspace_destroyed_on_runner_crash(self, tmp_path: Path) -> None:
        """When runner.fix() raises, the workspace should be destroyed."""
        loop, runner, _prs, state, workspaces = _make_loop_with_workspaces(tmp_path)
        runner.fix.side_effect = RuntimeError("runner exploded")
        state.get_diagnostic_attempts.return_value = []

        wt_path = loop._config.workspace_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        outcome = await loop._process_issue(42, "Bug title", "Bug body")

        assert outcome == "retry"
        workspaces.destroy.assert_awaited_once_with(42)
