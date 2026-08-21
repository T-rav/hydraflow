"""Regression #11551: implement lifecycle missing from READY queue counters.

``ImplementPhase`` records its workers through the real lifecycle helper with
the dashboard-facing stage name::

    src/implement_phase.py:473
    async with store_lifecycle(self._store, issue.id, "implement"):

but ``IssueStore`` keys its queues and counters on internal stage names
(``find``/``plan``/``ready``/``review``/``hitl`` — ``IssueStoreStage``), where
the READY stage is spelled ``"ready"`` and only *displayed* as ``implement``
via ``STAGE_NAME_MAP``. ``store_lifecycle`` forwards the stage string
verbatim (``phase_utils.py:450``), so a running implementer lands in
``_active`` under ``"implement"`` — a key that:

* ``get_queue_stats`` never counts (``issue_store.py:968`` iterates only the
  five canonical keys), so ``/api/queue.active_count.ready`` reads 0 while
  ``/api/pipeline`` shows the same worker active (the raw ``"implement"``
  string passes through ``STAGE_NAME_MAP`` at ``_routes.py:1616`` as a
  display name — the board works by accident);
* ``mark_complete`` never increments (``issue_store.py:642`` guards on
  ``stage in self._processed_count``), so ``total_processed.ready`` can never
  move for implementation work.

Live shape (2026-08-21 session): issue #11518 running from its canonical
implementation worktree — pipeline board active, gateway rows proving
inference, yet ``/api/queue.active_count.ready == 0``.

Pins:

* one running implementer (real ``store_lifecycle``, stage string taken from
  ``ImplementPhase``) must report ``active_count["ready"] == 1`` — RED today
  (reads 0);
* completing it must increment ``total_processed["ready"]`` exactly once —
  RED today (never increments);
* a plan worker still counts under ``plan`` for both active and processed —
  GREEN today and must stay green, proving the helper/store contract works
  when the names agree (isolates the defect to the implement→ready aliasing);
* the pipeline snapshot still surfaces the running implementer under the
  frontend ``implement`` stage — GREEN today via passthrough and must stay
  GREEN after the fix (the fix may normalize the store key, but the
  dashboard-facing name is preserved through ``STAGE_NAME_MAP``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from events import EventBus
from issue_store import STAGE_NAME_MAP, IssueStore
from phase_utils import store_lifecycle
from tests.helpers import ConfigFactory

# The stage string ImplementPhase passes to store_lifecycle
# (src/implement_phase.py:473) — and the issue whose live run exposed the
# mismatch. Dashboard-facing name for IssueStore's READY stage.
IMPLEMENT_STAGE = "implement"
LIVE_ISSUE = 11518


def _make_store() -> IssueStore:
    """Create a real IssueStore with standard test config and mocked fetcher."""
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=[])
    return IssueStore(ConfigFactory.create(), fetcher, EventBus())


async def test_running_implementer_counts_under_ready_active() -> None:
    """A worker held via store_lifecycle(..., "implement") must count as READY active."""
    store = _make_store()

    async with store_lifecycle(store, LIVE_ISSUE, IMPLEMENT_STAGE):
        stats = store.get_queue_stats()
        # /api/queue reads exactly this dict — the live #11518 mismatch.
        assert stats.active_count["ready"] == 1, (
            "running implementer invisible to READY active counter: "
            f"active_count={stats.active_count}"
        )
        # Exactly one worker, under exactly one bucket — no stray/legacy key.
        assert sum(stats.active_count.values()) == 1


async def test_implementer_completion_increments_ready_processed_once() -> None:
    """Exiting the implement lifecycle must increment the READY processed counter."""
    store = _make_store()

    async with store_lifecycle(store, LIVE_ISSUE, IMPLEMENT_STAGE):
        pass

    stats = store.get_queue_stats()
    assert stats.total_processed["ready"] == 1, (
        "implement completion never reached the READY processed counter: "
        f"total_processed={stats.total_processed}"
    )


async def test_plan_lifecycle_still_counts_plan_counters() -> None:
    """Control: stage names that agree with the store keys keep working.

    GREEN today — pins that the defect is specific to the implement→ready
    aliasing, not a general store_lifecycle/get_queue_stats breakage.
    """
    store = _make_store()

    async with store_lifecycle(store, 7, "plan"):
        stats = store.get_queue_stats()
        assert stats.active_count["plan"] == 1

    assert store.get_queue_stats().total_processed["plan"] == 1


async def test_pipeline_snapshot_keeps_frontend_implement_name() -> None:
    """The board must keep showing the running implementer as active.

    Maps raw snapshot keys through STAGE_NAME_MAP exactly as the
    /api/pipeline route does (_routes.py:1616). GREEN via passthrough today;
    must remain GREEN after the store-side normalization.
    """
    store = _make_store()

    async with store_lifecycle(store, LIVE_ISSUE, IMPLEMENT_STAGE):
        frontend_stages = {
            STAGE_NAME_MAP.get(stage, stage): entries
            for stage, entries in store.get_pipeline_snapshot().items()
        }

    active_numbers = [
        entry["issue_number"] for entry in frontend_stages.get(IMPLEMENT_STAGE, [])
    ]
    assert LIVE_ISSUE in active_numbers, (
        "pipeline snapshot lost the running implementer under the frontend "
        f"implement stage: {frontend_stages}"
    )
