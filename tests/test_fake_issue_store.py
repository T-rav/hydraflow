"""FakeIssueStore — IssueStorePort impl backed by FakeGitHub + in-memory cache."""

from __future__ import annotations

import pytest

from events import EventBus
from mockworld.fakes import FakeGitHub
from mockworld.fakes.fake_issue_store import FakeIssueStore


@pytest.mark.asyncio
async def test_get_returns_issue_from_underlying_github() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    issue = await store.get(1)

    assert issue.number == 1
    assert issue.title == "first"


@pytest.mark.asyncio
async def test_transition_updates_label() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    await store.transition(1, "hydraflow-ready", "hydraflow-planning")

    assert "hydraflow-ready" not in gh._issues[1].labels
    assert "hydraflow-planning" in gh._issues[1].labels


# ── Pipeline snapshot status + hitl_visited (#10509) ────────────────────
# The dashboard's stage timeline distinguishes a merged issue that skipped
# HITL from one that visited and recovered. Both the "current status" value
# and the persistent hitl_visited signal must be accurate — previously the
# fake stamped every hitl/merged entry with the generic PROCESSING status,
# which the frontend can't tell apart from an in-flight issue.


def test_snapshot_hitl_entry_has_hitl_status_not_processing() -> None:
    gh = FakeGitHub()
    gh.add_issue(50, "escalated", "body", labels=["hydraflow-hitl"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    snapshot = store.get_pipeline_snapshot()

    assert len(snapshot["hitl"]) == 1
    assert snapshot["hitl"][0]["status"] == "hitl"


def test_snapshot_hitl_entry_marks_hitl_visited_true() -> None:
    gh = FakeGitHub()
    gh.add_issue(51, "escalated", "body", labels=["hydraflow-hitl"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    snapshot = store.get_pipeline_snapshot()

    assert snapshot["hitl"][0].get("hitl_visited") is True


def test_snapshot_merged_entry_has_merged_status_not_processing() -> None:
    gh = FakeGitHub()
    gh.add_issue(52, "fixed", "body", labels=[])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    store.mark_merged(52)

    snapshot = store.get_pipeline_snapshot()

    assert len(snapshot["merged"]) == 1
    assert snapshot["merged"][0]["status"] == "merged"


def test_snapshot_merged_entry_hitl_visited_false_when_never_escalated() -> None:
    gh = FakeGitHub()
    gh.add_issue(53, "fixed", "body", labels=[])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    store.mark_merged(53)

    snapshot = store.get_pipeline_snapshot()

    assert snapshot["merged"][0].get("hitl_visited") is False


def test_snapshot_merged_entry_hitl_visited_true_when_previously_escalated() -> None:
    gh = FakeGitHub()
    gh.add_issue(54, "recovered", "body", labels=["hydraflow-hitl"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    # Observe the issue while it's in HITL so the visited-history is recorded.
    store.get_pipeline_snapshot()

    # Human resolved it; it moves on and eventually merges.
    gh._issues[54].labels = []
    store.mark_merged(54)

    snapshot = store.get_pipeline_snapshot()

    assert snapshot["merged"][0].get("hitl_visited") is True


def test_get_hitl_issues_persists_visited_history() -> None:
    gh = FakeGitHub()
    gh.add_issue(55, "escalated", "body", labels=["hydraflow-hitl"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    assert store.get_hitl_issues() == {55}

    gh._issues[55].labels = ["hydraflow-review"]

    assert store.get_hitl_issues() == set()
    assert 55 in store._hitl_visited
