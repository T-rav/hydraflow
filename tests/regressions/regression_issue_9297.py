"""Regression tests for issue #9297.

Bug: ``gh_shape_validator`` produced false-positive drift for three common call
patterns, causing 10 drift signatures to get stuck across 3+ loop ticks:

1. ``gh pr list --json number --jq length`` — the ``--jq`` flag transforms the
   output to a scalar (``'0'``), not a gh JSON shape.  The dispatcher was
   returning ``GhPRSummary`` and failing to validate the scalar.

2. ``gh issue list --json number,title,body,updatedAt`` — ``GhIssueSummary``
   requires ``state`` (not in the requested field set), so every well-formed
   result tripped a ``ValidationError``.

3. ``gh issue view N --json comments`` — ``{"comments":[]}`` has no ``number``
   or ``state``, again tripping ``GhIssueSummary`` validation.
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
async def test_jq_flag_skips_validation(tmp_path: Path) -> None:
    """``--jq`` transforms output to an arbitrary scalar — dispatcher should
    return None (no opinion) rather than attempting shape validation."""
    sample = _sample(
        tmp_path,
        args=[
            "pr",
            "list",
            "--head",
            "agent/issue-9278",
            "--state",
            "open",
            "--json",
            "number",
            "--jq",
            "length",
        ],
        stdout="0",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_list_without_state_validates_as_list_item(tmp_path: Path) -> None:
    """``gh issue list --json number,title,body,updatedAt`` omits ``state``.
    The dispatcher must not apply ``GhIssueSummary`` (which requires ``state``);
    it should use ``GhIssueListItem`` instead and pass cleanly."""
    sample = _sample(
        tmp_path,
        args=[
            "issue",
            "list",
            "--repo",
            "org/repo",
            "--label",
            "hitl-escalation",
            "--state",
            "closed",
            "--json",
            "number,title,body,updatedAt",
            "--limit",
            "200",
        ],
        stdout=json.dumps(
            [
                {
                    "number": 1,
                    "title": "HITL: trust-loop anomaly",
                    "body": "details",
                    "updatedAt": "2026-06-04T00:00:00Z",
                },
            ]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_view_comments_only_skipped(tmp_path: Path) -> None:
    """``gh issue view N --json comments`` returns ``{"comments":[]}``.
    No shape covers a payload with only ``comments``; dispatcher should return
    None (no opinion) rather than forcing ``GhIssueSummary`` and failing on
    missing ``number``/``state``."""
    sample = _sample(
        tmp_path,
        args=["issue", "view", "9291", "--json", "comments"],
        stdout=json.dumps({"comments": []}) + "\n",
    )
    assert await gh_shape_validator(sample) is None
