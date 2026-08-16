"""Scenario: the review loop discovers PRs under agent/auto-agent-{N} (#11282).

Bug: ``IssueFetcher.fetch_reviewable_prs`` only ever resolved a
``hydraflow-review``-labeled issue's PR via the ``agent/issue-{N}`` branch
pattern. PRs opened by the Auto-Agent preflight path live under
``agent/auto-agent-{N}`` (``AUTO_AGENT_BRANCH_PREFIX``) instead, so
``HydraFlowOrchestrator._review_single_issue`` — the real background review
loop's per-issue reaction — treated a genuinely open Auto-Agent PR as
non-existent ("review orphan"): it never called the reviewer, and instead
took the requeue/strike path that (after enough strikes) escalates to HITL.
Live symptom: PR #11310 (branch ``agent/auto-agent-11282``) never got
reviewed by the loop despite being open and failing CI.

Why this can't be a ``FakeIssueFetcher``-backed MockWorld scenario:
``FakeIssueFetcher.fetch_reviewable_prs`` (src/mockworld/fakes/
fake_issue_fetcher.py) matches a PR to an issue via the Fake's own
``issue_number`` bookkeeping field, not by parsing ``pr.branch`` — so it
never reproduced this bug regardless of branch string, and a scenario built
on it could not go red before the fix. This scenario instead builds the
REAL ``HydraFlowOrchestrator`` (real ``IssueFetcher`` included) and fakes
only the true I/O boundary ``IssueFetcher`` itself crosses —
``run_subprocess``'s ``gh api .../pulls`` call — matching the test-pyramid
standard's "Mocks at: Subprocess / network boundary only" for this layer.
The reviewer itself is stubbed (an ``AsyncMock``) since exercising a real
review is out of scope for this bug; what's under test is purely whether
the loop *discovers* the PR at all.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from config import AUTO_AGENT_BRANCH_PREFIX
from orchestrator import HydraFlowOrchestrator
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario_loops

_ISSUE_NUMBER = 11282
_PR_NUMBER = 11310


def _auto_agent_pr_batch_json() -> str:
    """A single open PR on the Auto-Agent branch, in ``gh api .../pulls`` shape."""
    return json.dumps(
        [
            {
                "number": _PR_NUMBER,
                "html_url": f"https://github.com/test-org/test-repo/pull/{_PR_NUMBER}",
                "draft": False,
                "head": {"ref": f"{AUTO_AGENT_BRANCH_PREFIX}{_ISSUE_NUMBER}"},
            }
        ]
    )


async def test_review_single_issue_discovers_pr_under_auto_agent_branch(
    tmp_path,
) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    orch = HydraFlowOrchestrator(config)

    review_issue = TaskFactory.create(
        id=_ISSUE_NUMBER,
        title="Factory Health Trends: methodology popovers",
        tags=["hydraflow-review"],
    )

    batch_json = _auto_agent_pr_batch_json()

    async def fake_run_subprocess(*_args: str, **_kwargs: object) -> str:
        return batch_json

    review_prs_mock = AsyncMock(return_value=[])
    orch._svc.reviewer.review_prs = review_prs_mock  # type: ignore[method-assign]
    orch._svc.reviewer.post_review_transcript_hooks = AsyncMock()  # type: ignore[method-assign]

    with patch("issue_fetcher.run_subprocess", side_effect=fake_run_subprocess):
        did_work = await orch._review_single_issue(review_issue)

    assert did_work is True, (
        "_review_single_issue must report real work done — a False here means "
        "it took the review-orphan requeue path, i.e. the PR was NOT discovered"
    )
    review_prs_mock.assert_awaited_once()
    await_args = review_prs_mock.await_args
    assert await_args is not None
    prs_arg = await_args.args[0]
    assert len(prs_arg) == 1, (
        "the real IssueFetcher.fetch_reviewable_prs must resolve the PR opened "
        f"under {AUTO_AGENT_BRANCH_PREFIX}{_ISSUE_NUMBER} and hand it to the "
        f"reviewer; got {prs_arg!r}"
    )
    assert prs_arg[0].number == _PR_NUMBER
    assert prs_arg[0].branch == f"{AUTO_AGENT_BRANCH_PREFIX}{_ISSUE_NUMBER}"
