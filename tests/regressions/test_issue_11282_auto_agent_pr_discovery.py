"""Regression test for issue #11282.

Bug: ``IssueFetcher.fetch_reviewable_prs`` (src/issue_fetcher.py) only ever
resolved a ``hydraflow-review``-labeled issue's PR via the
``agent/issue-{N}`` branch pattern. PRs opened by the Auto-Agent preflight
path live under ``agent/auto-agent-{N}`` (``AUTO_AGENT_BRANCH_PREFIX`` in
config.py) instead, so an open Auto-Agent PR with a CI failure was never
resolved here — the review/fix-forward loop could never find it to feed the
failure back into a new commit. Symptom on the live factory: PR #11310
(branch ``agent/auto-agent-11282``) sat with a failing CI Gate while repeated
review-loop attempts reported "nothing to do" / "already committed" instead
of converging, because the loop never saw the PR in the first place.

Fix: check both branch patterns against the batch-fetched
``{branch: pr_data}`` map, preferring the manual ``agent/issue-{N}`` branch
if both somehow have an open PR for the same issue.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from config import AUTO_AGENT_BRANCH_PREFIX, HydraFlowConfig  # noqa: E402
from issue_fetcher import IssueFetcher  # noqa: E402

_ISSUE_NUMBER = 11282

_RAW_ISSUE_JSON = json.dumps(
    [
        {
            "number": _ISSUE_NUMBER,
            "title": "Factory Health Trends: methodology popovers",
            "body": "Details",
            "labels": [{"name": "hydraflow-review"}],
            "comments": [],
            "url": f"https://github.com/test-org/test-repo/issues/{_ISSUE_NUMBER}",
        }
    ]
)


def _batch_pr_json(branch: str) -> str:
    """A single open-PR REST payload on *branch*, matching the ``/pulls`` shape."""
    return json.dumps(
        [
            {
                "number": 11310,
                "html_url": "https://github.com/test-org/test-repo/pull/11310",
                "draft": False,
                "head": {"ref": branch},
            }
        ]
    )


def _fake_run(batch_json: str):
    async def fake_run(*args: str, **_kwargs: Any) -> str:
        if any("issues" in arg for arg in args):
            return _RAW_ISSUE_JSON
        return batch_json

    return fake_run


@pytest.mark.asyncio
async def test_fetch_reviewable_prs_finds_pr_under_auto_agent_branch(
    config: HydraFlowConfig,
) -> None:
    fetcher = IssueFetcher(config)
    branch = f"{AUTO_AGENT_BRANCH_PREFIX}{_ISSUE_NUMBER}"

    with patch(
        "issue_fetcher.run_subprocess", side_effect=_fake_run(_batch_pr_json(branch))
    ):
        prs, issues = await fetcher.fetch_reviewable_prs(set())

    assert len(issues) == 1
    assert len(prs) == 1, (
        "a PR opened under the Auto-Agent branch pattern "
        f"({branch!r}) must be discoverable by fetch_reviewable_prs, not "
        "silently dropped because only agent/issue-{N} was checked"
    )
    assert prs[0].number == 11310
    assert prs[0].issue_number == _ISSUE_NUMBER
    assert prs[0].branch == branch
