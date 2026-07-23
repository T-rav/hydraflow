"""Regression test for issue #10299.

Bug: epic child execution state was LABEL-derived. ``EpicManager._build_child_info``
stamped a child ``RUNNING`` whenever it carried an ``implement``/``review``
label (``src/epic.py`` ~919), and ``_build_detail`` counted such children into
``EpicDetail.active_children``. The result: the Epics panel showed a green
``active`` badge for an epic even when NO worker was actually on any child, and
``EpicChildInfo.worker`` was never populated.

Fix: derive running/queued from worker ground truth (``IssueStore._active`` ∪
``_in_flight`` for running, ``IssueStore`` stage queues for queued) instead of
labels. A child with an implement label but no worker holding it must read
``queued`` (or drop out of the counts entirely when parked), and a worker-held
child must read ``running`` with ``worker`` populated.

This test pins the exact bug: an implement-labeled, unheld child must NOT be
``running`` and must NOT inflate ``active_children``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC))

from epic import EpicManager
from events import EventBus
from state import StateTracker
from tests.conftest import IssueFactory
from tests.helpers import ConfigFactory


class _FakeWorkerStore:
    """``issue_number -> stage`` worker-truth maps (WorkerTruthStore surface)."""

    def __init__(
        self,
        worker_held: dict[int, str] | None = None,
        queued: dict[int, str] | None = None,
    ) -> None:
        self._worker_held = dict(worker_held or {})
        self._queued = dict(queued or {})

    def get_worker_held_issues(self) -> dict[int, str]:
        return dict(self._worker_held)

    def get_queued_issues(self) -> dict[int, str]:
        return dict(self._queued)


def _make_manager(tmp_path: Path, store: _FakeWorkerStore):
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        state_file=tmp_path / "state.json",
    )
    state = StateTracker(config.state_file)
    prs = AsyncMock()
    prs.find_open_pr_for_branch = AsyncMock(return_value=None)
    fetcher = AsyncMock()
    manager = EpicManager(
        config, state, prs, fetcher, EventBus(), issue_store=store
    )
    return manager, fetcher


@pytest.mark.asyncio
async def test_implement_labeled_unheld_child_is_not_running(tmp_path: Path) -> None:
    """An implement-labeled child that no worker holds must not read running."""
    # No worker holds #10; it merely sits in the ready queue.
    store = _FakeWorkerStore(queued={10: "ready"})
    mgr, fetcher = _make_manager(tmp_path, store)
    await mgr.register_epic(100, "Epic", [10])
    # ``test-label`` is the configured ready/implement label — the exact input
    # that used to force RUNNING under the old label-derived logic.
    fetcher.fetch_issue_by_number = AsyncMock(
        return_value=IssueFactory.create(
            number=10, title="Waiting", labels=["test-label"]
        )
    )

    detail = await mgr.get_detail(100)

    assert detail is not None
    assert detail.children[0].status == "queued", "label alone must not imply running"
    assert detail.active_children == 0, "unheld child must not count as active"
    assert detail.queued_children == 1


@pytest.mark.asyncio
async def test_worker_held_child_populates_worker(tmp_path: Path) -> None:
    """A worker-held child reads running and populates the dormant worker field."""
    store = _FakeWorkerStore(worker_held={10: "ready"})
    mgr, fetcher = _make_manager(tmp_path, store)
    await mgr.register_epic(100, "Epic", [10])
    fetcher.fetch_issue_by_number = AsyncMock(
        return_value=IssueFactory.create(
            number=10, title="Held", labels=["test-label"]
        )
    )

    detail = await mgr.get_detail(100)

    assert detail is not None
    assert detail.children[0].status == "running"
    assert detail.children[0].worker == "ready", "worker must be populated (#10299)"
    assert detail.active_children == 1
