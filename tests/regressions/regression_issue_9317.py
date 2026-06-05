"""Regression tests for issue #9317.

12 drift signatures survived LiveCorpusReplayLoop's 3-tick retry budget because
gh_shape_validator generated false-positive validation errors for two classes of
call patterns:

1. **Narrow --json queries on issue-list and pr-checks** that don't request all
   required shape fields:
   - ``gh issue list --json createdAt,closedAt`` — GhIssueListItem requires
     number+title; date-only queries omit both.
   - ``gh pr checks --json conclusion`` — GhCheckRun requires name; conclusion-only
     queries omit it.

2. **Completed check runs** where ``gh pr checks --json state`` returns terminal
   conclusion values (SUCCESS, FAILURE, SKIPPED, etc.) in the ``state`` field —
   _GhCheckState only listed in-progress statuses so every finished check failed.

Fixes:
- _pick_shape_for_issue_list guards on number+title before returning GhIssueListItem.
- _pick_shape_for_checks guards on name before returning GhCheckRun.
- _GhCheckState expanded to include terminal conclusion values.
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


# ── Narrow issue-list and pr-checks patterns ─────────────────────────────────


@pytest.mark.asyncio
async def test_issue_list_date_only_skipped(tmp_path: Path) -> None:
    """``gh issue list --json createdAt,closedAt`` omits number+title — skip."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "createdAt,closedAt"],
        stdout=json.dumps([{"createdAt": "2026-06-01T00:00:00Z", "closedAt": None}])
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_list_number_only_skipped(tmp_path: Path) -> None:
    """``gh issue list --json number`` omits title — skip."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "number"],
        stdout=json.dumps([{"number": 1}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_conclusion_only_skipped(tmp_path: Path) -> None:
    """``gh pr checks --json conclusion`` omits required name field — skip."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "42", "--json", "conclusion"],
        stdout=json.dumps([{"conclusion": "SUCCESS"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_state_only_skipped(tmp_path: Path) -> None:
    """``gh pr checks --json state`` omits required name field — skip."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "42", "--json", "state"],
        stdout=json.dumps([{"state": "SUCCESS"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


# ── GhCheckState terminal values ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_run_success_state_validates_cleanly(tmp_path: Path) -> None:
    """``gh pr checks --json name,state`` with state=SUCCESS must not drift."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "42", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci / build", "state": "SUCCESS"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_check_run_failure_state_validates_cleanly(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "42", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci / lint", "state": "FAILURE"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_check_run_skipped_state_validates_cleanly(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "42", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci / deploy", "state": "SKIPPED"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_check_run_neutral_state_validates_cleanly(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "42", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci / optional", "state": "NEUTRAL"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


# ── Full required-field queries still validate correctly ─────────────────────


@pytest.mark.asyncio
async def test_issue_list_with_number_and_title_validates(tmp_path: Path) -> None:
    """Full required-field issue-list query must not be blocked by guard."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "number,title,body,updatedAt"],
        stdout=json.dumps([{"number": 9317, "title": "drift test", "body": "x"}])
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_with_name_and_state_validates(tmp_path: Path) -> None:
    """Full required-field pr-checks query must not be blocked by guard."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "42", "--json", "name,state,conclusion"],
        stdout=json.dumps(
            [{"name": "ci / build", "state": "COMPLETED", "conclusion": "SUCCESS"}]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None
