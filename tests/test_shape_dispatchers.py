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


@pytest.mark.asyncio
async def test_shape_failure_dict_uses_shape_verdict_key_constant(
    tmp_path: Path,
) -> None:
    """gh_shape_validator must embed SHAPE_VERDICT_KEY (not a literal string) so
    the LiveCorpusReplayLoop's compare-time suppression for VOLATILE shapes can
    detect a real shape failure vs a raw-value difference."""
    from contracts.shadow_classifier import SHAPE_VERDICT_KEY

    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,title,state"],
        stdout=json.dumps([{"number": 1, "title": "x", "state": "QUEUED"}]) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert SHAPE_VERDICT_KEY in result
    assert result[SHAPE_VERDICT_KEY] is True


# ---------------------------------------------------------------------------
# gh_shape_covers (#9633) — record-time coverage predicate derived from the
# same _select_shape helper the validator dispatches through, so coverage
# and dispatcher opinion can never drift apart.
# ---------------------------------------------------------------------------


COVERED_ARGS: list[list[str]] = [
    ["pr", "view", "42", "--json", "number,title,state"],
    ["pr", "list", "--json", "number,title,state"],
    ["pr", "view", "42", "--json", "number,mergeable,headRefName"],
    ["issue", "view", "7", "--json", "number,state"],
    ["issue", "list", "--json", "number,title"],
    ["pr", "checks", "42", "--json", "name,state"],
]

UNCOVERED_ARGS: list[list[str]] = [
    ["api", "search/issues", "--jq", ".total_count"],
    ["pr", "view", "42", "--json", "number,title,state", "--jq", ".number"],
    ["pr", "view", "42", "--json", "headRefOid"],
    ["pr", "view", "42"],
    ["pr", "create", "--title", "x"],
    ["issue", "create", "--title", "x"],
    ["repo", "clone", "x"],
    ["status"],
]


@pytest.mark.parametrize("args", COVERED_ARGS, ids=" ".join)
def test_gh_shape_covers_true_for_dispatcher_covered_args(args: list[str]) -> None:
    """Every args shape _select_shape picks a model for is covered."""
    from contracts.shape_dispatchers import gh_shape_covers

    assert gh_shape_covers(args) is True


@pytest.mark.parametrize("args", UNCOVERED_ARGS, ids=" ".join)
def test_gh_shape_covers_false_for_no_opinion_args(args: list[str]) -> None:
    """--jq transforms, narrow projections, mutations, and unknown
    subcommands can never produce a dispatcher opinion."""
    from contracts.shape_dispatchers import gh_shape_covers

    assert gh_shape_covers(args) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("args", UNCOVERED_ARGS, ids=" ".join)
async def test_uncovered_args_imply_validator_has_no_opinion(
    tmp_path: Path, args: list[str]
) -> None:
    """Consistency property: gh_shape_covers(args) is False ⇒ the validator
    returns None for those args, whatever the stdout. Coverage pruning can
    never drop a sample the validator would have validated."""
    from contracts.shape_dispatchers import gh_shape_covers

    assert gh_shape_covers(args) is False
    sample = _sample(
        tmp_path,
        args=args,
        stdout='{"number": 1, "title": "x", "state": "OPEN"}\n',
    )
    assert await gh_shape_validator(sample) is None
