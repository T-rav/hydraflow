"""Regression tests for issue #9314.

Five shadow-corpus call patterns produced false-positive drift signals because
``gh_shape_validator`` attempted shape validation even when the requested
``--json`` fields didn't include all required fields for the chosen model:

1. ``gh pr view N --json commits`` — ``GhPRSummary`` requires ``number``,
   ``title``, ``state``; the response only has ``commits``.

2. ``gh pr view N --json reviews`` — same required fields missing.

3. ``gh pr view N --json headRefOid`` — ``headRefOid`` is a detail-signal so
   ``GhPRDetail`` is selected, but ``GhPRDetail`` requires ``number`` which
   isn't in the requested field set.

4. ``gh issue view N --json state,stateReason`` — ``GhIssueSummary`` requires
   ``number`` and ``state``; the call omits ``number``.

5. ``gh pr list --json number,labels,body,commits`` — ``GhPRSummary`` requires
   ``title`` and ``state``; both are absent from the field set.

The fix: ``_pick_shape_for_pr`` and ``_pick_shape_for_issue`` now guard on the
required fields of the target shape before returning it.  When required fields
are absent from the requested set, the dispatcher returns ``None`` (no opinion)
instead of attempting validation that is guaranteed to fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.shadow import ShadowCorpus
from contracts.shape_dispatchers import gh_shape_validator


def _sample(
    tmp_path: Path,
    *,
    args: list[str],
    stdout: str,
    adapter: str = "github",
    command: str = "gh",
):
    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter=adapter,
        command=command,
        args=args,
        stdout=stdout,
        stderr="",
        exit_code=0,
    )
    assert path is not None
    return corpus.load(path)


@pytest.mark.asyncio
async def test_pr_view_commits_only_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json commits`` returns a ``commits`` array; the
    response omits ``number``, ``title``, ``state`` that ``GhPRSummary``
    requires.  The dispatcher must return None rather than a false drift."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--repo", "org/repo", "--json", "commits"],
        stdout=json.dumps(
            {"commits": [{"oid": "abc1234", "messageHeadline": "fix: something"}]}
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_reviews_only_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json reviews`` returns a ``reviews`` array; the
    response omits the required fields for any PR shape."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--repo", "org/repo", "--json", "reviews"],
        stdout=json.dumps(
            {"reviews": [{"state": "APPROVED", "author": {"login": "alice"}}]}
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_head_ref_oid_only_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json headRefOid`` — ``headRefOid`` triggers the detail
    signal so ``GhPRDetail`` would be selected, but ``GhPRDetail`` requires
    ``number`` which is absent.  Must return None."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--repo", "org/repo", "--json", "headRefOid"],
        stdout=json.dumps({"headRefOid": "def5678abcdef" * 3}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_view_state_statereason_only_skipped(tmp_path: Path) -> None:
    """``gh issue view N --json state,stateReason`` omits ``number`` which
    ``GhIssueSummary`` requires.  Dispatcher must return None."""
    sample = _sample(
        tmp_path,
        args=[
            "issue",
            "view",
            "9314",
            "--repo",
            "org/repo",
            "--json",
            "state,stateReason",
        ],
        stdout=json.dumps({"state": "CLOSED", "stateReason": "COMPLETED"}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_list_narrow_fields_skipped(tmp_path: Path) -> None:
    """``gh pr list --json number,labels,body,commits`` omits ``title`` and
    ``state`` that ``GhPRSummary`` requires.  Dispatcher must return None."""
    sample = _sample(
        tmp_path,
        args=[
            "pr",
            "list",
            "--repo",
            "org/repo",
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,labels,body,commits",
        ],
        stdout=json.dumps(
            [
                {
                    "number": 100,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": "Fixes #99",
                    "commits": [{"oid": "abc1234"}],
                }
            ]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


# Confirm that well-formed calls still validate — the fix must not suppress
# genuine drift signals.


@pytest.mark.asyncio
async def test_pr_view_full_summary_fields_still_validates(tmp_path: Path) -> None:
    """A PR view with number,title,state present still routes to GhPRSummary
    and catches a real drift (bad state value)."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "number,title,state"],
        stdout=json.dumps({"number": 42, "title": "Fix it", "state": "QUEUED"}) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape"] == "GhPRSummary"


@pytest.mark.asyncio
async def test_pr_view_detail_with_number_still_validates(tmp_path: Path) -> None:
    """A PR detail view with number present still routes to GhPRDetail
    and catches a real drift (bad mergeable value)."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "number,headRefName,mergeable"],
        stdout=json.dumps(
            {"number": 42, "headRefName": "feat/x", "mergeable": "PROBABLY"}
        )
        + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape"] == "GhPRDetail"


@pytest.mark.asyncio
async def test_issue_view_with_number_and_state_still_validates(tmp_path: Path) -> None:
    """An issue view with number,state present still routes to GhIssueSummary
    and catches a real drift (bad state value)."""
    sample = _sample(
        tmp_path,
        args=["issue", "view", "9314", "--json", "number,state,stateReason"],
        stdout=json.dumps({"number": 9314, "state": "ARCHIVED", "stateReason": None})
        + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape"] == "GhIssueSummary"
