"""Unit tests for the issue_fetcher closure built in build_services.

The fetcher is extracted and tested in isolation by monkeypatching the
_run_gh seam on a stub PRManager-like object.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from service_registry import _make_fitness_issue_fetcher

ISSUE_OPEN = {
    "number": 1,
    "state": "OPEN",
    "labels": [{"name": "bug"}, {"name": "ready"}],
    "createdAt": "2026-06-01T10:00:00Z",
    "closedAt": None,
}

ISSUE_CLOSED = {
    "number": 2,
    "state": "CLOSED",
    "labels": [{"name": "planner"}],
    "createdAt": "2026-05-01T08:00:00Z",
    "closedAt": "2026-05-15T12:00:00Z",
}

PR_MERGED = {
    "number": 3,
    "state": "MERGED",
    "labels": [{"name": "review"}],
    "createdAt": "2026-06-10T09:00:00Z",
    "closedAt": "2026-06-11T14:00:00Z",
    "mergedAt": "2026-06-11T14:00:00Z",
}

PR_OPEN = {
    "number": 4,
    "state": "OPEN",
    "labels": [],
    "createdAt": "2026-06-25T07:00:00Z",
    "closedAt": None,
    "mergedAt": None,
}


@pytest.fixture()
def fake_prs():
    """Stub with _run_gh that returns canned JSON for issue and PR calls."""
    prs = MagicMock()
    prs._repo = "owner/repo"

    async def _run_gh(*args):
        args_str = " ".join(args)
        if "gh issue list" in args_str or ("issue" in args_str and "list" in args_str):
            return json.dumps([ISSUE_OPEN, ISSUE_CLOSED])
        if "gh pr list" in args_str or ("pr" in args_str and "list" in args_str):
            return json.dumps([PR_MERGED, PR_OPEN])
        return "[]"

    prs._run_gh = _run_gh
    return prs


def test_open_issue_mapping(fake_prs):
    fetcher = _make_fitness_issue_fetcher(fake_prs)
    records = asyncio.run(fetcher())
    open_issue = next(r for r in records if r.number == 1)
    assert open_issue.is_pr is False
    assert open_issue.state == "open"
    assert open_issue.merged is False
    assert "bug" in open_issue.labels
    assert "ready" in open_issue.labels


def test_closed_issue_mapping(fake_prs):
    fetcher = _make_fitness_issue_fetcher(fake_prs)
    records = asyncio.run(fetcher())
    closed_issue = next(r for r in records if r.number == 2)
    assert closed_issue.is_pr is False
    assert closed_issue.state == "closed"
    assert closed_issue.merged is False
    assert closed_issue.closed_at is not None
    assert isinstance(closed_issue.closed_at, datetime)


def test_merged_pr_mapping(fake_prs):
    fetcher = _make_fitness_issue_fetcher(fake_prs)
    records = asyncio.run(fetcher())
    merged_pr = next(r for r in records if r.number == 3)
    assert merged_pr.is_pr is True
    assert merged_pr.merged is True
    assert "review" in merged_pr.labels


def test_open_pr_not_merged(fake_prs):
    fetcher = _make_fitness_issue_fetcher(fake_prs)
    records = asyncio.run(fetcher())
    open_pr = next(r for r in records if r.number == 4)
    assert open_pr.is_pr is True
    assert open_pr.merged is False
    assert open_pr.labels == []
    assert open_pr.closed_at is None


def test_labels_mapped_to_strings(fake_prs):
    fetcher = _make_fitness_issue_fetcher(fake_prs)
    records = asyncio.run(fetcher())
    for record in records:
        assert all(isinstance(lbl, str) for lbl in record.labels)


def test_timestamps_are_datetimes(fake_prs):
    fetcher = _make_fitness_issue_fetcher(fake_prs)
    records = asyncio.run(fetcher())
    for record in records:
        assert isinstance(record.created_at, datetime)
        if record.closed_at is not None:
            assert isinstance(record.closed_at, datetime)
