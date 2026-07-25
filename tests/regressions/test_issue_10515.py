"""Regression #10515: FakeIssueStore stamps HITL/merged snapshot entries as PROCESSING.

``FakeIssueStore.get_pipeline_snapshot`` built the STAGE_HITL and STAGE_MERGED
buckets with ``PipelineIssueStatus.PROCESSING``, while the real
``IssueStore._snapshot_hitl`` / ``_snapshot_merged`` (``src/issue_store.py``)
stamp ``"hitl"`` and ``"merged"``. A MockWorld scenario asserting on
terminal-bucket status was therefore testing behaviour the production store
does not have. These tests pin the Fake to the real store's wire vocabulary:
HITL entries carry ``PipelineIssueStatus.HITL`` and merged entries carry
``PipelineIssueStatus.MERGED``.
"""

from __future__ import annotations

from events import EventBus
from mockworld.fakes import FakeGitHub
from mockworld.fakes.fake_issue_store import FakeIssueStore
from models import PipelineIssueStatus


def test_hitl_bucket_is_empty_when_no_hitl_issues() -> None:
    gh = FakeGitHub()
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    snapshot = store.get_pipeline_snapshot()

    assert snapshot["hitl"] == []


def test_hitl_bucket_stamps_status_hitl_not_processing() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "needs a human", "body", labels=["hydraflow-hitl"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    snapshot = store.get_pipeline_snapshot()

    assert len(snapshot["hitl"]) == 1
    assert snapshot["hitl"][0]["status"] == PipelineIssueStatus.HITL
    assert snapshot["hitl"][0]["status"] != PipelineIssueStatus.PROCESSING


def test_multiple_hitl_issues_are_all_stamped_hitl() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-hitl"])
    gh.add_issue(2, "second", "body", labels=["hydraflow-hitl"])
    gh.add_issue(3, "third", "body", labels=["hydraflow-hitl"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    snapshot = store.get_pipeline_snapshot()

    assert len(snapshot["hitl"]) == 3
    assert all(
        entry["status"] == PipelineIssueStatus.HITL for entry in snapshot["hitl"]
    )


def test_merged_bucket_is_empty_when_no_merged_issues() -> None:
    gh = FakeGitHub()
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    snapshot = store.get_pipeline_snapshot()

    assert snapshot["merged"] == []


def test_merged_bucket_stamps_status_merged_not_processing() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "shipped", "body", labels=[])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    store.mark_merged(1)

    snapshot = store.get_pipeline_snapshot()

    assert len(snapshot["merged"]) == 1
    assert snapshot["merged"][0]["status"] == PipelineIssueStatus.MERGED
    assert snapshot["merged"][0]["status"] != PipelineIssueStatus.PROCESSING


def test_multiple_merged_issues_are_all_stamped_merged() -> None:
    gh = FakeGitHub()
    for num in (1, 2, 3):
        gh.add_issue(num, f"issue {num}", "body", labels=[])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    for num in (1, 2, 3):
        store.mark_merged(num)

    snapshot = store.get_pipeline_snapshot()

    assert len(snapshot["merged"]) == 3
    assert all(
        entry["status"] == PipelineIssueStatus.MERGED for entry in snapshot["merged"]
    )
