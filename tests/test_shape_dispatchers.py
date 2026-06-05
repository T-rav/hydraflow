"""Unit tests for the Pydantic shape dispatcher (Phase 5 of #8786)."""

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
    """Helper: record a sample to a temp corpus and return the loaded view."""
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
async def test_valid_pr_summary_returns_none(tmp_path: Path) -> None:
    """A well-shaped gh pr list payload validates cleanly → None (no drift)."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,title,state"],
        stdout=json.dumps(
            [
                {"number": 1, "title": "x", "state": "OPEN"},
                {"number": 2, "title": "y", "state": "MERGED"},
            ]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_drifted_pr_state_enum_returns_diff(tmp_path: Path) -> None:
    """A new gh state value not in the Literal trips validation → drift dict."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,title,state"],
        stdout=json.dumps([{"number": 1, "title": "x", "state": "QUEUED"}]) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape_validation_failed"] is True
    assert result["shape"] == "GhPRSummary"
    assert result["failure_count"] == 1


@pytest.mark.asyncio
async def test_pr_view_picks_detail_shape(tmp_path: Path) -> None:
    """``--json mergeable,headRefName`` is the detail-shape signal."""
    sample = _sample(
        tmp_path,
        args=[
            "pr",
            "view",
            "42",
            "--json",
            "number,headRefName,baseRefName,mergeable",
        ],
        stdout=json.dumps(
            {
                "number": 42,
                "headRefName": "feat/x",
                "baseRefName": "staging",
                "mergeable": "MERGEABLE",
            }
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_drifted_mergeable_enum(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "number,mergeable"],
        stdout=json.dumps({"number": 42, "mergeable": "PROBABLY"}) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape"] == "GhPRDetail"


@pytest.mark.asyncio
async def test_issue_view_validates_against_issue_summary(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["issue", "view", "7", "--json", "number,state,stateReason"],
        stdout=json.dumps({"number": 7, "state": "CLOSED", "stateReason": "completed"})
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_non_gh_adapter_skipped(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        adapter="git",
        command="git",
        args=["commit", "-m", "x"],
        stdout="[main abc1234] x\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_no_json_flag_skipped(tmp_path: Path) -> None:
    """Plain ``gh pr view 42`` (no --json) returns human text, not validated."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42"],
        stdout="title: x\nstate: open\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_empty_stdout_skipped(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number"],
        stdout="",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_non_json_stdout_skipped(tmp_path: Path) -> None:
    """Subcommand says --json but stdout is malformed — skip rather than fail
    loudly. A real recorder bug would surface elsewhere."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number"],
        stdout="not actually json\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_list_without_state_validates_cleanly(tmp_path: Path) -> None:
    """gh issue list --json number,title omits 'state' (filtered server-side).

    Previously routed to GhIssueSummary which requires state, producing
    spurious drift for every issue-list shadow sample (signature 5653c1c6d466).
    Now routed to GhIssueListItem which only requires number and title.
    """
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "number,title"],
        stdout=json.dumps(
            [
                {"number": 9278, "title": "Drift survived LiveCorpusReplayLoop"},
                {"number": 9100, "title": "Another open issue"},
            ]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_list_drifted_number_type_returns_diff(tmp_path: Path) -> None:
    """issue-list with a wrong-typed number field trips GhIssueListItem validation."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "number,title"],
        stdout=json.dumps([{"number": "not-an-int", "title": "x"}]) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape_validation_failed"] is True
    assert result["shape"] == "GhIssueListItem"


@pytest.mark.asyncio
async def test_unknown_subcommand_skipped(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["api", "graphql", "--json", "data"],
        stdout='{"data": {}}\n',
    )
    assert await gh_shape_validator(sample) is None


# --- Regression tests for false-positive drift signatures (issue #9321) ---
# These calls produce output whose fields don't match GhPRSummary/GhIssueSummary
# required fields — the dispatcher must return None (no opinion) rather than
# applying the wrong shape and generating spurious drift.


@pytest.mark.asyncio
async def test_pr_view_commits_only_skipped(tmp_path: Path) -> None:
    """gh pr view N --json commits: no state/detail signals → no opinion."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "commits"],
        stdout=json.dumps({"commits": [{"oid": "abc123", "messageHeadline": "fix: x"}]})
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_reviews_only_skipped(tmp_path: Path) -> None:
    """gh pr view N --json reviews: no state/detail signals → no opinion."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "reviews"],
        stdout=json.dumps(
            {"reviews": [{"state": "APPROVED", "author": {"login": "alice"}}]}
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_title_body_skipped(tmp_path: Path) -> None:
    """gh pr view N --json title,body: missing state → no opinion (GhPRSummary requires state)."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "title,body"],
        stdout=json.dumps({"title": "fix: bug", "body": "closes #41"}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_list_number_labels_body_skipped(tmp_path: Path) -> None:
    """gh pr list --json number,labels,body: missing state → no opinion."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,labels,body"],
        stdout=json.dumps(
            [{"number": 1, "labels": [{"name": "bug"}], "body": "fixes #1"}]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_view_state_reason_only_skipped(tmp_path: Path) -> None:
    """gh issue view N --json state,stateReason: missing number → no opinion.

    GhIssueSummary requires number; calls omitting it must be skipped to
    avoid false-positive drift (stuck signature in issue #9321).
    """
    sample = _sample(
        tmp_path,
        args=["issue", "view", "7", "--json", "state,stateReason"],
        stdout=json.dumps({"state": "CLOSED", "stateReason": "completed"}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_list_title_only_skipped(tmp_path: Path) -> None:
    """gh issue list --json title: missing number → no opinion.

    GhIssueListItem requires number; calls omitting it must be skipped to
    avoid false-positive drift (pattern from rc_budget_loop dedup checks).
    """
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "title"],
        stdout=json.dumps([{"title": "fix: stuck drift"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_view_with_number_and_state_validates(tmp_path: Path) -> None:
    """gh issue view N --json number,state,stateReason: both required fields → GhIssueSummary used."""
    sample = _sample(
        tmp_path,
        args=["issue", "view", "7", "--json", "number,state,stateReason"],
        stdout=json.dumps({"number": 7, "state": "CLOSED", "stateReason": "completed"})
        + "\n",
    )
    assert await gh_shape_validator(sample) is None
