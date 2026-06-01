"""MockWorld scenario: pipeline membership changes push PIPELINE_SNAPSHOT.

The third leg of the test pyramid for the WS pipeline-snapshot push (PR3).
Unit tests in ``tests/test_issue_store.py::TestPipelineSnapshotPush`` cover the
coalescing/seq/re-check mechanics against a bare ``IssueStore``; this scenario
drives the *real* ``IssueStore`` wired into a ``MockWorld`` (via the shared
``PipelineHarness`` — same ``EventBus`` the dashboard subscribes to) and asserts
the load-bearing integration contract:

* When an issue is picked up / transitions in a MockWorld-driven store, a
  ``PIPELINE_SNAPSHOT`` is published to the bus.
* The payload is keyed by the FRONTEND stage name (``implement``), not the
  backend ``IssueStoreStage`` value (``ready``) — byte-identical to what the
  ``GET /api/pipeline`` REST poll would serve, so the WS push is authoritative.
* The snapshot arrives WITHOUT any REST poll: the harness fetcher (the only
  GitHub-fetch surface) is never invoked. The push is event-driven off the
  in-memory mutation, not a poll of ``GET /api/pipeline``.
* (PR5 stale-snapshot regression) The pushed snapshot is delivered LIVE to a
  subscriber but is NOT retained in ``bus.get_history()`` — so a WS reconnect,
  which replays ``get_history()`` on connect, can never re-deliver a stale
  historical snapshot that would clobber the freshly-fetched board state. This
  is the integration-level proof that the ephemeral mechanism in
  ``events.EPHEMERAL_EVENT_TYPES`` closes the clobber vector on the real bus the
  dashboard subscribes to.

Limitation (noted per task brief): ``MockWorld.run_with_loops`` invokes
``loop._do_work()`` against catalog-allocated mock ports, which does not route
through the harness's shared ``IssueStore``/bus, so it cannot assert
bus events at the IssueStore level. We therefore drive the store through the
same pickup/transition API the phases use (``get_triageable`` →
``enqueue_transition``) on the harness's real store + real bus — the minimal
realistic scenario that exercises the snapshot push at the store/bus boundary.
"""

from __future__ import annotations

from events import EventType
from issue_store import STAGE_NAME_MAP, STAGE_READY
from tests.conftest import TaskFactory

# No scenario_loops marker: this scenario drives the harness's real
# IssueStore + EventBus directly (not via LoopCatalog.run_with_loops), so it
# runs in the default suite alongside tests/scenarios/test_telemetry_e2e.py
# and tests/scenarios/test_mock_world_apply_seed.py rather than the loop tier.


def _drain_snapshots(queue):
    """Drain PIPELINE_SNAPSHOT frames live-delivered to a subscriber queue.

    PIPELINE_SNAPSHOT is ephemeral (PR5): fanned out to subscribers but never
    retained in ``get_history()``. Assert against the live subscriber — the same
    delivery path the dashboard WS uses — not history.
    """
    import asyncio

    out = []
    while True:
        try:
            event = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if event.type == EventType.PIPELINE_SNAPSHOT:
            out.append(event)
    return out


async def _drain_snapshot_flush(store) -> None:
    """Await the store's coalesced snapshot flush task (debounce + publish)."""
    task = store._snapshot_flush_task
    if task is not None:
        await task


class TestPipelineSnapshotScenario:
    """A pickup/transition in a MockWorld-driven store pushes a snapshot."""

    async def test_transition_pushes_frontend_keyed_snapshot_without_rest_poll(
        self, mock_world
    ) -> None:
        world = mock_world
        harness = world.harness
        store = harness.store
        bus = harness.bus

        # Subscribe BEFORE mutating: snapshots are live-only and won't appear in
        # history, so the subscriber is the sole capture surface.
        queue = bus.subscribe()

        # Seed the find queue the way a GitHub refresh would, then assert the
        # fetcher (the sole REST-poll surface) is untouched: the push is driven
        # off in-memory mutation, not a GET /api/pipeline poll.
        issue = TaskFactory.create(
            id=909,
            title="Wire the snapshot push",
            tags=["hydraflow-find"],
            source_url="https://github.com/test-org/test-repo/issues/909",
        )
        store._route_issues([issue])

        # Pickup: triage phase dequeues from find (→ in-flight) then advances
        # the issue to the ready/implement stage — the canonical membership
        # change a real phase performs.
        picked = store.get_triageable(1)
        assert picked and picked[0].id == 909
        store.enqueue_transition(issue, "ready")

        await _drain_snapshot_flush(store)

        snaps = _drain_snapshots(queue)
        assert snaps, "membership change must push a PIPELINE_SNAPSHOT to the bus"

        snap = snaps[-1]
        assert isinstance(snap.data["seq"], int)
        stages = snap.data["stages"]

        # Frontend stage key, not the backend IssueStoreStage value.
        assert STAGE_NAME_MAP[STAGE_READY] == "implement"
        assert "implement" in stages, f"expected frontend key; got {list(stages)}"
        assert "ready" not in stages
        entry = stages["implement"][0]
        assert entry["issue_number"] == 909
        assert set(entry).issuperset({"issue_number", "title", "url", "status"})

        # The snapshot reached the bus with no GitHub fetch: it is a push off the
        # in-memory mutation, not a REST poll re-render.
        harness.fetcher.fetch_all.assert_not_called()

        # PR5 stale-snapshot regression: the snapshot was delivered LIVE but is
        # NOT in history. A WS reconnect replays get_history() on connect; if a
        # PIPELINE_SNAPSHOT lived there, a stale historical frame could land
        # after the fresh REST sync and clobber the board (worst on an idle
        # pipeline). Asserting its absence here proves the clobber vector is
        # closed on the real bus the dashboard subscribes to.
        replayed_on_reconnect = bus.get_history()
        assert all(
            e.type != EventType.PIPELINE_SNAPSHOT for e in replayed_on_reconnect
        ), "PIPELINE_SNAPSHOT must not enter WS reconnect replay (get_history)"
