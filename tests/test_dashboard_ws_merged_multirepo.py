"""Phase 4 — merged WebSocket + /api/events backfill for ``repo=__all__``.

The aggregate view fans in every registered repo's event bus over a single
``/ws`` socket and a single ``/api/events`` backfill. These tests pin:

* the pure merge/forward helpers (sort by ``(timestamp, id)``, repo-tagging,
  skip-a-down-bus, drop-oldest on a full shared queue), and
* the end-to-end socket: ``?repo=__all__`` streams a merged, repo-tagged history
  and does NOT 1008-close when one repo is down (a single down line must not
  stop the whole aggregate stream / frontend reconnect).

The single-repo fast path (``None`` / specific slug) stays in
``tests/test_dashboard_websocket.py`` and is unchanged.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from events import EventBus, EventType, HydraFlowEvent
from tests.helpers import find_endpoint, make_dashboard_router, make_registry

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from state import StateTracker

pytestmark = pytest.mark.integration


def _evt(
    data: dict,
    ts: str,
    *,
    repo: str | None = None,
    event_id: int | None = None,
    event_type: EventType = EventType.WORKER_UPDATE,
) -> HydraFlowEvent:
    kwargs: dict = {"type": event_type, "data": data, "timestamp": ts}
    if repo is not None:
        kwargs["repo"] = repo
    if event_id is not None:
        kwargs["id"] = event_id
    return HydraFlowEvent(**kwargs)


def _runtime(bus: object, slug: str) -> tuple:
    """A resolve_runtimes 5-tuple (config, state, bus, get_orch, slug)."""
    return (None, None, bus, lambda: None, slug)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestMergeSortedHistory:
    def test_orders_by_timestamp_then_id_and_tags_repo(self) -> None:
        from dashboard_routes._routes import _merge_sorted_history

        bus_a = EventBus()
        bus_b = EventBus()
        # Untagged history (repo=None) → the merge stamps each with its bus slug.
        bus_a._history = [_evt({"i": 1}, "2024-01-01T00:00:01+00:00", event_id=1)]
        bus_b._history = [_evt({"i": 2}, "2024-01-01T00:00:00+00:00", event_id=2)]

        merged = _merge_sorted_history(
            [_runtime(bus_a, "owner-alpha"), _runtime(bus_b, "owner-beta")]
        )

        # bus_b's event has the earlier timestamp → first.
        assert [(e.repo, e.data["i"]) for e in merged] == [
            ("owner-beta", 2),
            ("owner-alpha", 1),
        ]

    def test_id_breaks_timestamp_ties(self) -> None:
        from dashboard_routes._routes import _merge_sorted_history

        bus_a = EventBus()
        bus_b = EventBus()
        same_ts = "2024-01-01T00:00:00+00:00"
        bus_a._history = [_evt({"i": 10}, same_ts, event_id=10)]
        bus_b._history = [_evt({"i": 5}, same_ts, event_id=5)]

        merged = _merge_sorted_history(
            [_runtime(bus_a, "owner-alpha"), _runtime(bus_b, "owner-beta")]
        )

        assert [e.id for e in merged] == [5, 10]

    def test_preserves_existing_repo_tag(self) -> None:
        from dashboard_routes._routes import _merge_sorted_history

        bus = EventBus()
        bus._history = [_evt({"i": 1}, "2024-01-01T00:00:00+00:00", repo="real-repo")]

        merged = _merge_sorted_history([_runtime(bus, "fallback-slug")])

        # An already-tagged event keeps its repo, not the resolved slug.
        assert merged[0].repo == "real-repo"

    def test_skips_a_down_bus(self) -> None:
        from dashboard_routes._routes import _merge_sorted_history

        ok = EventBus()
        ok._history = [_evt({"i": 1}, "2024-01-01T00:00:01+00:00", event_id=1)]

        class _DownBus:
            def get_history(self) -> list:
                raise RuntimeError("repo down")

        merged = _merge_sorted_history(
            [_runtime(ok, "owner-alpha"), _runtime(_DownBus(), "owner-beta")]
        )

        assert len(merged) == 1
        assert merged[0].repo == "owner-alpha"


class TestForwardToMerged:
    @pytest.mark.asyncio
    async def test_tags_repo_and_forwards(self) -> None:
        from dashboard_routes._routes import _forward_to_merged

        src: asyncio.Queue = asyncio.Queue()
        dst: asyncio.Queue = asyncio.Queue()
        src.put_nowait(_evt({"i": 1}, "2024-01-01T00:00:00+00:00"))  # repo=None

        task = asyncio.create_task(_forward_to_merged(src, dst, "owner-alpha"))
        out = await asyncio.wait_for(dst.get(), timeout=1)
        task.cancel()

        assert out.repo == "owner-alpha"

    @pytest.mark.asyncio
    async def test_drops_oldest_when_shared_queue_full(self) -> None:
        from dashboard_routes._routes import _forward_to_merged

        src: asyncio.Queue = asyncio.Queue()
        dst: asyncio.Queue = asyncio.Queue(maxsize=1)
        dst.put_nowait(_evt({"i": 0}, "2024-01-01T00:00:00+00:00", repo="owner-beta"))
        fresh = _evt({"i": 1}, "2024-01-01T00:00:01+00:00", repo="owner-beta")
        src.put_nowait(fresh)

        task = asyncio.create_task(_forward_to_merged(src, dst, "owner-beta"))
        await asyncio.sleep(0.05)
        task.cancel()

        # The full queue dropped the oldest and kept the fresh frame.
        remaining = dst.get_nowait()
        assert remaining.data["i"] == 1


# ---------------------------------------------------------------------------
# /ws integration
# ---------------------------------------------------------------------------


def _seed(bus: EventBus, slug: str, events: list[HydraFlowEvent]) -> None:
    bus.set_repo(slug)

    async def _pub() -> None:
        for e in events:
            await bus.publish(e)

    asyncio.run(_pub())


class TestMergedWebSocket:
    def test_repo_all_streams_merged_repo_tagged_history(
        self, config: HydraFlowConfig, event_bus: EventBus, state: StateTracker
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        bus_a = EventBus()
        bus_b = EventBus()
        _seed(bus_a, "owner-alpha", [_evt({"i": 1}, "2024-01-01T00:00:01+00:00")])
        _seed(bus_b, "owner-beta", [_evt({"i": 2}, "2024-01-01T00:00:02+00:00")])

        registry = make_registry(
            {"slug": "owner-alpha", "event_bus": bus_a, "running": True},
            {"slug": "owner-beta", "event_bus": bus_b, "running": True},
        )
        dashboard = HydraFlowDashboard(
            config,
            event_bus,
            state,
            registry=registry,
            default_repo_slug="owner-alpha",
        )
        client = TestClient(dashboard.create_app())

        with client.websocket_connect("/ws?repo=__all__") as ws:
            m1 = json.loads(ws.receive_text())
            m2 = json.loads(ws.receive_text())

        assert (m1["repo"], m1["data"]["i"]) == ("owner-alpha", 1)
        assert (m2["repo"], m2["data"]["i"]) == ("owner-beta", 2)

    @pytest.mark.asyncio
    async def test_empty_runtimes_closes_cleanly_without_hanging(self) -> None:
        from unittest.mock import AsyncMock

        from dashboard_routes._routes import _serve_merged_ws

        ws = AsyncMock()

        # An empty aggregate (no runtimes) must close cleanly, not block forever
        # on an out-queue nothing can feed.
        await asyncio.wait_for(_serve_merged_ws(ws, []), timeout=2)

        ws.accept.assert_awaited_once()
        ws.close.assert_awaited_once_with(code=1000)

    def test_repo_all_does_not_1008_when_a_repo_is_down(
        self, config: HydraFlowConfig, event_bus: EventBus, state: StateTracker
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        ok = EventBus()
        _seed(ok, "owner-alpha", [_evt({"i": 1}, "2024-01-01T00:00:01+00:00")])

        class _DownBus:
            def get_history(self) -> list:
                return []

            def subscription(self) -> object:
                raise RuntimeError("repo down")

        registry = make_registry(
            {"slug": "owner-alpha", "event_bus": ok, "running": True},
            {"slug": "owner-beta", "event_bus": _DownBus(), "running": True},
        )
        dashboard = HydraFlowDashboard(
            config, event_bus, state, registry=registry, default_repo_slug="owner-alpha"
        )
        client = TestClient(dashboard.create_app())

        # If the merged socket 1008-closed on the down repo, receive_text would
        # raise instead of yielding the healthy repo's history frame.
        with client.websocket_connect("/ws?repo=__all__") as ws:
            msg = json.loads(ws.receive_text())

        assert msg["data"]["i"] == 1
        assert msg["repo"] == "owner-alpha"


# ---------------------------------------------------------------------------
# /api/events backfill merge
# ---------------------------------------------------------------------------


class TestEventsBackfillMerge:
    @pytest.mark.asyncio
    async def test_repo_all_merges_and_sorts_tagged(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path,
    ) -> None:
        bus_a = EventBus()
        bus_b = EventBus()
        # Already inside a running loop (async test) — await publishes directly.
        bus_a.set_repo("owner-alpha")
        bus_b.set_repo("owner-beta")
        await bus_a.publish(_evt({"i": 1}, "2024-01-01T00:00:01+00:00"))
        await bus_b.publish(_evt({"i": 2}, "2024-01-01T00:00:02+00:00"))

        registry = make_registry(
            {"slug": "owner-alpha", "event_bus": bus_a, "running": True},
            {"slug": "owner-beta", "event_bus": bus_b, "running": True},
        )
        router, _pr = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            registry=registry,
            default_repo_slug="owner-alpha",
        )
        endpoint = find_endpoint(router, "/api/events")

        resp = await endpoint(since=None, repo="__all__")
        data = json.loads(resp.body)

        assert [(e["repo"], e["data"]["i"]) for e in data] == [
            ("owner-alpha", 1),
            ("owner-beta", 2),
        ]
