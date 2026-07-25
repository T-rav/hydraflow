"""Regression: issue #10493 — implement_phase must recover the PR from an
already-pushed branch instead of stranding committed+pushed work.

Root cause: the long local verification step (e.g. browser/scenario) gets
reaped by a subprocess timeout AFTER commit+push but BEFORE the PR-open step,
leaving a real diff on the pushed branch with no PR. ``_handle_no_pr_fallback``
then marked the issue ``"failed"``, bouncing it back to ``hydraflow-ready`` for
a full rebuild — even though the fix was already committed and pushed.

Fix (idempotent recovery): when the branch has a diff, re-check for an open PR
and, if none, open one from the pushed branch — mirroring the happy path — then
mark the issue into the post-create state (``success`` + ``review`` transition)
and return ``success=True``. Only a genuine ``create_pr`` failure falls through
to the old "mark failed / retry" behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.conftest import PRInfoFactory, TaskFactory, WorkerResultFactory
from tests.helpers import ImplementPhaseMockBuilder

if TYPE_CHECKING:
    from config import HydraFlowConfig


@pytest.mark.asyncio
async def test_no_pr_with_diff_recovers_pr_instead_of_stranding(
    config: HydraFlowConfig,
) -> None:
    """A pushed branch with a real diff and no PR must be recovered, not failed.

    This is the core of #10493: instead of marking the issue ``failed`` (which
    rebuilds the already-delivered work from scratch), ``_handle_no_pr_fallback``
    opens the PR from the pushed branch and advances the issue to review.
    """
    issue = TaskFactory.create()
    result = WorkerResultFactory.create(
        issue_number=42,
        success=True,
        workspace_path=str(config.workspace_path_for_issue(42)),
    )
    recovered_pr = PRInfoFactory.create(number=777, issue_number=42)

    phase, _, mock_prs = (
        ImplementPhaseMockBuilder(config)
        .with_issues([issue])
        .with_create_pr_return(recovered_pr)
        .with_prs_method("find_open_pr_for_branch", AsyncMock(return_value=None))
        .with_prs_method("branch_has_diff_from_main", AsyncMock(return_value=True))
        .build()
    )

    returned = await phase._handle_no_pr_fallback(issue, result)

    # Recovery opened the PR from the already-pushed branch...
    mock_prs.create_pr.assert_awaited_once()
    # ...delivered the work instead of stranding it...
    assert returned.success is True
    assert returned.pr_info is recovered_pr
    # ...marked the issue into the happy-path post-create state (NOT "failed")...
    assert phase._state.to_dict()["processed_issues"].get(str(42)) == "success"
    # ...and drove the review transition with the recovered PR number.
    mock_prs.transition.assert_awaited_once()
    assert mock_prs.transition.await_args.kwargs.get("pr_number") == 777


@pytest.mark.asyncio
async def test_no_pr_with_diff_uses_existing_pr_without_recreating(
    config: HydraFlowConfig,
) -> None:
    """If a PR appeared since the initial resolve, reuse it — don't re-create."""
    issue = TaskFactory.create()
    result = WorkerResultFactory.create(
        issue_number=42,
        success=True,
        workspace_path=str(config.workspace_path_for_issue(42)),
    )
    existing_pr = PRInfoFactory.create(number=555, issue_number=42)

    phase, _, mock_prs = (
        ImplementPhaseMockBuilder(config)
        .with_issues([issue])
        .with_prs_method("find_open_pr_for_branch", AsyncMock(return_value=existing_pr))
        .with_prs_method("branch_has_diff_from_main", AsyncMock(return_value=True))
        .build()
    )

    returned = await phase._handle_no_pr_fallback(issue, result)

    mock_prs.find_open_pr_for_branch.assert_awaited()
    mock_prs.create_pr.assert_not_awaited()
    assert returned.success is True
    assert returned.pr_info is existing_pr
    assert phase._state.to_dict()["processed_issues"].get(str(42)) == "success"


@pytest.mark.asyncio
async def test_recovery_create_pr_failure_falls_through_to_failed(
    config: HydraFlowConfig,
) -> None:
    """Only a genuine PR-open failure keeps the old mark-failed/retry behaviour."""
    issue = TaskFactory.create()
    result = WorkerResultFactory.create(
        issue_number=42,
        success=True,
        workspace_path=str(config.workspace_path_for_issue(42)),
    )

    phase, _, mock_prs = (
        ImplementPhaseMockBuilder(config)
        .with_issues([issue])
        # create_pr returns the number=0 sentinel → recovery genuinely failed.
        .with_create_pr_return(PRInfoFactory.create(number=0))
        .with_prs_method("find_open_pr_for_branch", AsyncMock(return_value=None))
        .with_prs_method("branch_has_diff_from_main", AsyncMock(return_value=True))
        .build()
    )

    returned = await phase._handle_no_pr_fallback(issue, result)

    mock_prs.create_pr.assert_awaited_once()
    assert returned.success is False
    assert returned.error == "PR creation failed"
    assert phase._state.to_dict()["processed_issues"].get(str(42)) == "failed"
    mock_prs.transition.assert_not_awaited()
