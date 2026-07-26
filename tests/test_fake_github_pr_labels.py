"""FakeGitHub.get_pr_labels — in-memory PR-scoped label read (#10567)."""

from __future__ import annotations

import pytest

from mockworld.fakes import FakeGitHub


@pytest.mark.asyncio
async def test_get_pr_labels_returns_seeded_labels() -> None:
    gh = FakeGitHub()
    gh.add_pr(number=100, issue_number=1, branch="hf/issue-1")
    gh.add_pr_label(100, "needs-review")
    gh.add_pr_label(100, "priority-high")

    labels = await gh.get_pr_labels(100)

    assert labels == ["needs-review", "priority-high"]


@pytest.mark.asyncio
async def test_get_pr_labels_empty_for_unknown_pr() -> None:
    gh = FakeGitHub()

    labels = await gh.get_pr_labels(999)

    assert labels == []
