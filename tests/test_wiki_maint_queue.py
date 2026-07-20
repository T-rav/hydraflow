"""Tests for src/wiki_maint_queue.py — Phase 4 admin-task queue.

Covers enqueue, drain, and JSON persistence across restarts so
console-triggered mark-stale / force-compile / rebuild-index tasks
survive a factory restart before the next ``RepoWikiLoop`` tick runs.
"""

from __future__ import annotations

from pathlib import Path

REPO = "acme/widget"


def test_enqueue_then_drain_returns_tasks_in_order(tmp_path: Path) -> None:
    from wiki_maint_queue import MaintenanceQueue, MaintenanceTask

    q = MaintenanceQueue(path=tmp_path / "q.json")
    q.enqueue(
        MaintenanceTask(
            kind="force-compile", repo_slug=REPO, params={"topic": "patterns"}
        )
    )
    q.enqueue(
        MaintenanceTask(
            kind="mark-stale",
            repo_slug=REPO,
            params={"entry_id": "0042", "reason": "stale"},
        )
    )

    drained = q.drain()
    assert [t.kind for t in drained] == ["force-compile", "mark-stale"]
    assert drained[1].params["entry_id"] == "0042"


def test_drain_empties_the_queue(tmp_path: Path) -> None:
    from wiki_maint_queue import MaintenanceQueue, MaintenanceTask

    q = MaintenanceQueue(path=tmp_path / "q.json")
    q.enqueue(MaintenanceTask(kind="rebuild-index", repo_slug=REPO, params={}))
    q.drain()

    assert q.drain() == []
    assert q.peek() == []


def test_peek_does_not_drain(tmp_path: Path) -> None:
    from wiki_maint_queue import MaintenanceQueue, MaintenanceTask

    q = MaintenanceQueue(path=tmp_path / "q.json")
    q.enqueue(MaintenanceTask(kind="rebuild-index", repo_slug=REPO, params={}))

    assert len(q.peek()) == 1
    assert len(q.peek()) == 1  # still there


def test_persistence_survives_restart(tmp_path: Path) -> None:
    from wiki_maint_queue import MaintenanceQueue, MaintenanceTask

    path = tmp_path / "q.json"
    q1 = MaintenanceQueue(path=path)
    q1.enqueue(MaintenanceTask(kind="rebuild-index", repo_slug=REPO, params={}))

    q2 = MaintenanceQueue(path=path)
    drained = q2.drain()
    assert len(drained) == 1
    assert drained[0].kind == "rebuild-index"


def test_drain_clears_persisted_file(tmp_path: Path) -> None:
    from wiki_maint_queue import MaintenanceQueue, MaintenanceTask

    path = tmp_path / "q.json"
    q1 = MaintenanceQueue(path=path)
    q1.enqueue(MaintenanceTask(kind="rebuild-index", repo_slug=REPO, params={}))
    q1.drain()

    # Fresh loader must also see an empty queue — not the pre-drain state.
    q2 = MaintenanceQueue(path=path)
    assert q2.peek() == []


def test_corrupt_json_returns_empty_queue(tmp_path: Path) -> None:
    """A malformed queue file must not crash startup.

    Factory restart needs to stay robust; worst case we silently reset
    the queue and let admins re-enqueue.
    """
    from wiki_maint_queue import MaintenanceQueue

    path = tmp_path / "q.json"
    path.write_text("{not valid json]")

    q = MaintenanceQueue(path=path)
    assert q.peek() == []


def test_rejects_unknown_kind() -> None:
    """``kind`` is constrained to the known action values."""
    import pytest

    from wiki_maint_queue import MaintenanceTask

    with pytest.raises(ValueError, match="kind must be"):
        MaintenanceTask(kind="launch-rocket", repo_slug=REPO, params={})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ingest-entry kind + worktree-isolated ingest routing (#9836)
# ---------------------------------------------------------------------------


def _entry():
    from repo_wiki import WikiEntry

    return WikiEntry(
        title="An insight",
        content="Body.",
        topic="gotchas",
        source_type="review",
        source_issue=9,
    )


def test_ingest_entry_task_round_trips(tmp_path: Path) -> None:
    from repo_wiki import WikiEntry
    from wiki_maint_queue import MaintenanceQueue, make_ingest_entry_task

    q = MaintenanceQueue(path=tmp_path / "q.json")
    q.enqueue(make_ingest_entry_task(REPO, _entry()))

    task = q.peek()[0]
    assert task.kind == "ingest-entry"
    assert task.repo_slug == REPO
    # The payload rebuilds into an equivalent WikiEntry.
    rebuilt = WikiEntry.model_validate(task.params["entry"])
    assert rebuilt.title == "An insight"
    assert rebuilt.topic == "gotchas"


def test_drain_kinds_is_selective(tmp_path: Path) -> None:
    from wiki_maint_queue import (
        MaintenanceQueue,
        MaintenanceTask,
        make_ingest_entry_task,
    )

    q = MaintenanceQueue(path=tmp_path / "q.json")
    q.enqueue(MaintenanceTask(kind="rebuild-index", repo_slug=REPO, params={}))
    q.enqueue(make_ingest_entry_task(REPO, _entry()))

    ingest = q.drain_kinds(["ingest-entry"])
    assert [t.kind for t in ingest] == ["ingest-entry"]
    # The admin task is untouched.
    assert [t.kind for t in q.peek()] == ["rebuild-index"]


def test_enqueue_visible_across_instances_on_same_path(tmp_path: Path) -> None:
    """A long-lived instance (loop) must see an enqueue made by a transient
    instance (merge path) — reload-under-lock, not stale in-memory state."""
    from wiki_maint_queue import MaintenanceQueue, make_ingest_entry_task

    path = tmp_path / "q.json"
    loop_view = MaintenanceQueue(path=path)  # constructed first, empty snapshot

    transient = MaintenanceQueue(path=path)
    transient.enqueue(make_ingest_entry_task(REPO, _entry()))

    drained = loop_view.drain_kinds(["ingest-entry"])
    assert len(drained) == 1


def test_enqueue_wiki_ingest_writes_default_path(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from wiki_maint_queue import (
        MaintenanceQueue,
        default_queue_path,
        enqueue_wiki_ingest,
    )

    cfg = MagicMock()
    cfg.data_path = tmp_path.joinpath

    assert enqueue_wiki_ingest(cfg, REPO, [_entry(), _entry()]) == 2
    tasks = MaintenanceQueue(path=default_queue_path(cfg)).peek()
    assert [t.kind for t in tasks] == ["ingest-entry", "ingest-entry"]


def test_enqueue_wiki_ingest_noop_without_repo(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from wiki_maint_queue import enqueue_wiki_ingest

    cfg = MagicMock()
    cfg.data_path = tmp_path.joinpath
    assert enqueue_wiki_ingest(cfg, "", [_entry()]) == 0
