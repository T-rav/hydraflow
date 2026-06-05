"""Regression: partial-field gh calls must not generate false drift signatures.

Issue #9299 — LiveCorpusReplayLoop accumulated 11 stuck drift signatures
because ``gh_shape_validator`` validated partial-field gh responses against
shapes that require fields not present in the response:

  * ``gh pr view N --json commits``       → only "commits", but GhPRSummary
    requires "number", "title", "state"
  * ``gh issue view N --json state,stateReason`` → missing "number" required
    by GhIssueSummary
  * ``gh pr list --json number,labels,body`` → missing "title","state" for
    GhPRSummary

The fix adds required-field coverage guards to every _pick_shape_for_* helper
so that partial fetches return None (no opinion) instead of forcing the sample
through an incompatible shape.
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
async def test_partial_pr_view_commits_returns_none(tmp_path: Path) -> None:
    """gh pr view N --json commits omits number/title/state → no false drift."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "commits"],
        stdout=json.dumps({"commits": [{"oid": "abc123"}]}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_partial_issue_view_state_reason_returns_none(tmp_path: Path) -> None:
    """gh issue view N --json state,stateReason omits number → no false drift."""
    sample = _sample(
        tmp_path,
        args=["issue", "view", "9299", "--json", "state,stateReason"],
        stdout=json.dumps({"state": "OPEN", "stateReason": None}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_partial_pr_list_no_title_returns_none(tmp_path: Path) -> None:
    """gh pr list --json number,labels,body omits title/state → no false drift."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,labels,body"],
        stdout=json.dumps([{"number": 1, "labels": [], "body": "desc"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_partial_pr_view_reviews_returns_none(tmp_path: Path) -> None:
    """gh pr view N --json reviews omits required fields → no false drift."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "reviews"],
        stdout=json.dumps({"reviews": []}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_full_pr_summary_still_validates(tmp_path: Path) -> None:
    """A full gh pr list payload with all required fields still validates cleanly."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,title,state"],
        stdout=json.dumps([{"number": 1, "title": "fix", "state": "OPEN"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_full_issue_summary_still_detects_drift(tmp_path: Path) -> None:
    """A full gh issue view payload with an invalid state value still drifts."""
    sample = _sample(
        tmp_path,
        args=["issue", "view", "9299", "--json", "number,title,state,labels,body"],
        stdout=json.dumps(
            {
                "number": 9299,
                "title": "Test",
                "state": "INVALID_STATE",
                "labels": [],
                "body": "",
            }
        )
        + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape_validation_failed"] is True
