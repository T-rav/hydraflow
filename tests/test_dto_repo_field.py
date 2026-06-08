"""The four scoping DTOs carry an optional repo tag defaulting to empty string."""

from __future__ import annotations

from models import (
    BackgroundWorkerStatus,
    HITLItem,
    IssueHistoryEntry,
    PipelineIssue,
)


def test_pipeline_issue_repo_defaults_empty() -> None:
    assert PipelineIssue(issue_number=1).repo == ""


def test_pipeline_issue_repo_set_via_model_copy() -> None:
    issue = PipelineIssue(issue_number=1).model_copy(update={"repo": "owner-repo"})
    assert issue.repo == "owner-repo"


def test_hitl_item_repo_defaults_empty_and_serializes_flat() -> None:
    item = HITLItem(issue=1, repo="owner-repo")
    assert item.repo == "owner-repo"
    assert item.model_dump(by_alias=True)["repo"] == "owner-repo"


def test_background_worker_status_repo_defaults_empty() -> None:
    assert BackgroundWorkerStatus(name="x", label="y").repo == ""


def test_issue_history_entry_repo_defaults_empty() -> None:
    assert IssueHistoryEntry(issue_number=1).repo == ""
