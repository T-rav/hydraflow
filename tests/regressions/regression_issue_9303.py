"""Regression tests for issue #9303.

Bug: ``gh_shape_validator`` produced false-positive drift for narrow ``--json``
field queries whose requested fields don't cover a shape's required fields.
Seven drift signatures got stuck across 3+ loop ticks.

The patterns that caused false positives:

1. ``gh pr view N --json commits`` — no detail signal, routed to GhPRSummary
   which requires number+title+state; ``{"commits":[]}`` satisfies none.

2. ``gh pr view N --json reviews`` — no detail signal, same GhPRSummary path.

3. ``gh pr view N --json headRefOid`` — IS a detail signal (GhPRDetail), but
   GhPRDetail requires ``number``; ``{"headRefOid":"abc"}`` is missing it.

4. ``gh pr view N --json title,body`` — no state or number → GhPRSummary fails.

5. ``gh pr list --json number,labels,body`` — missing title+state.

6. ``gh pr list --json number,mergedAt,title,files`` — missing state.

7. ``gh issue list --json createdAt,closedAt`` — GhIssueListItem requires
   number+title; date-only queries satisfy neither.

Fix: ``gh_shape_validator`` now checks that the requested fields are a superset
of the chosen shape's required fields before attempting validation.  Narrow
queries return None (no opinion) rather than false-positive drift.
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
    """``gh pr view N --json commits`` omits required GhPRSummary fields.
    Dispatcher must return None, not a false-positive drift signal."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "commits"],
        stdout=json.dumps({"commits": [{"oid": "abc1234"}]}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_reviews_only_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json reviews`` has no detail signal and omits
    required GhPRSummary fields — must be skipped, not false-positive."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "reviews"],
        stdout=json.dumps(
            {"reviews": [{"state": "APPROVED", "author": {"login": "dev"}}]}
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_head_ref_oid_only_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json headRefOid`` triggers GhPRDetail (detail signal)
    but omits required ``number`` field — must be skipped."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "headRefOid"],
        stdout=json.dumps({"headRefOid": "abc1234567890"}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_title_body_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json title,body`` omits number and state.
    GhPRSummary requires all three — must be skipped."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "title,body"],
        stdout=json.dumps({"title": "Fix the thing", "body": "Details here"}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_list_number_labels_body_skipped(tmp_path: Path) -> None:
    """``gh pr list --json number,labels,body`` omits title and state.
    GhPRSummary requires both — must be skipped."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,labels,body"],
        stdout=json.dumps([{"number": 1, "labels": [], "body": "..."}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_list_without_state_skipped(tmp_path: Path) -> None:
    """``gh pr list --json number,mergedAt,title,files`` omits state.
    GhPRSummary requires state — must be skipped."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,mergedAt,title,files"],
        stdout=json.dumps(
            [
                {
                    "number": 5,
                    "mergedAt": "2026-06-04T00:00:00Z",
                    "title": "x",
                    "files": [],
                }
            ]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_list_date_fields_only_skipped(tmp_path: Path) -> None:
    """``gh issue list --json createdAt,closedAt`` omits number and title.
    GhIssueListItem requires both — must be skipped."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "createdAt,closedAt"],
        stdout=json.dumps(
            [
                {
                    "createdAt": "2026-06-01T00:00:00Z",
                    "closedAt": "2026-06-04T00:00:00Z",
                }
            ]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_with_required_fields_still_validates(tmp_path: Path) -> None:
    """Full GhPRSummary fields → validation still runs and catches real drift."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,title,state"],
        stdout=json.dumps([{"number": 1, "title": "x", "state": "UNKNOWN_STATE"}])
        + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape_validation_failed"] is True


@pytest.mark.asyncio
async def test_pr_checks_without_name_skipped(tmp_path: Path) -> None:
    """``gh pr checks --json conclusion`` omits name.
    GhCheckRun requires name — must be skipped."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "42", "--json", "conclusion"],
        stdout=json.dumps([{"conclusion": "SUCCESS"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None
