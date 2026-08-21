"""FakeIssueStore — IssueStorePort impl backed by FakeGitHub + in-memory cache."""

from __future__ import annotations

import pytest

from events import EventBus
from mockworld.fakes import FakeGitHub
from mockworld.fakes.fake_issue_store import FakeIssueStore
from tests.conftest import TaskFactory


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


def test_try_claim_stage_requires_matching_unowned_stage() -> None:
    gh = FakeGitHub()
    gh.add_issue(2, "planned", "body", labels=["hydraflow-plan"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    task = store.get_plannable(1)[0]
    store.release_in_flight({2})

    assert store.try_claim_stage(task, "plan") is True
    assert store.try_claim_stage(task, "plan") is False


def test_try_claim_stage_rejects_nonmatching_fake_stage() -> None:
    gh = FakeGitHub()
    gh.add_issue(4, "planned", "body", labels=["hydraflow-plan"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    task = store.get_plannable(1)[0]
    store.release_in_flight({4})

    assert store.try_claim_stage(task, "ready") is False


def test_try_claim_stage_rejects_hitl_like_production_store() -> None:
    gh = FakeGitHub()
    gh.add_issue(8, "escalated", "body", labels=["hydraflow-hitl"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    task = TaskFactory.create(id=8, tags=["hydraflow-hitl"])

    assert store.try_claim_stage(task, "hitl") is False
    assert store.get_worker_held_issues() == {}


def test_try_claim_stage_rejects_merged_fake_issue() -> None:
    gh = FakeGitHub()
    gh.add_issue(5, "merged", "body", labels=["hydraflow-plan"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    task = store.get_plannable(1)[0]
    store.release_in_flight({5})
    store.mark_merged(5)

    assert store.try_claim_stage(task, "plan") is False


def test_scoped_release_preserves_different_fake_stage_claim() -> None:
    gh = FakeGitHub()
    gh.add_issue(3, "ready", "body", labels=["hydraflow-ready"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    assert [task.id for task in store.get_implementable(1)] == [3]

    store.release_in_flight({3}, expected_stage="plan")

    assert store.get_worker_held_issues() == {3: "ready"}


@pytest.mark.asyncio
async def test_matching_scoped_release_stays_dequeued_until_refresh() -> None:
    gh = FakeGitHub()
    gh.add_issue(6, "planned", "body", labels=["hydraflow-plan"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    initial = store.get_plannable(1)
    assert [task.id for task in initial] == [6]

    store.release_in_flight({6}, expected_stage="plan")

    assert store.get_plannable(1) == []
    assert store.try_claim_stage(initial[0], "plan") is False
    await store.refresh()
    refreshed = store.get_plannable(1)
    assert [task.id for task in refreshed] == [6]
    store.release_in_flight({6})
    assert store.try_claim_stage(refreshed[0], "plan") is True


def test_clear_active_removes_fake_stage_release_suppression() -> None:
    gh = FakeGitHub()
    gh.add_issue(7, "planned", "body", labels=["hydraflow-plan"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())
    assert [task.id for task in store.get_plannable(1)] == [7]
    store.release_in_flight({7}, expected_stage="plan")
    assert store.get_plannable(1) == []

    store.clear_active()

    assert [task.id for task in store.get_plannable(1)] == [7]


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


def test_mark_active_with_dashboard_name_counts_against_its_stage() -> None:
    """Parity with IssueStore (#11551): ``"implement"`` is the READY counter."""
    gh = FakeGitHub()
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    store.mark_active(5, "implement")
    assert store.get_queue_stats().active_count["ready"] == 1

    store.mark_complete(5)
    stats = store.get_queue_stats()
    assert stats.active_count["ready"] == 0
    assert stats.total_processed["ready"] == 1


def test_fake_display_name_map_mirrors_the_real_store() -> None:
    """The Fake keeps its own stage vocabulary; it must not drift (#11551)."""
    from issue_store import STAGE_NAME_MAP, IssueStoreStage, resolve_issue_store_stage
    from mockworld.fakes import fake_issue_store

    real_inverse = {display: str(stage) for stage, display in STAGE_NAME_MAP.items()}
    assert real_inverse == fake_issue_store._DISPLAY_NAME_TO_STAGE
    for name in [*STAGE_NAME_MAP.values(), *(s.value for s in IssueStoreStage), "x"]:
        real = resolve_issue_store_stage(name)
        assert fake_issue_store._resolve_stage(name) == (
            None if real is None else str(real)
        )
