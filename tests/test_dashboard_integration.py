"""Integration coverage for dashboard HTTP + WebSocket surfaces."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from events import EventType
from tests.conftest import EventFactory

if TYPE_CHECKING:
    from tests.conftest import DashboardAppBundle


def _publish_events(bus, *events) -> None:
    async def _run() -> None:
        for event in events:
            await bus.publish(event)

    asyncio.run(_run())


def test_state_endpoint_serializes_tracker(dashboard_app: DashboardAppBundle) -> None:
    state = dashboard_app.state
    state.mark_issue(77, "review")
    state.set_branch(77, "feature/network-tests")
    state.set_hitl_cause(77, "needs triage eyes")

    client = TestClient(dashboard_app.app)
    response = client.get("/api/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_issues"]["77"] == "review"
    assert payload["active_branches"]["77"] == "feature/network-tests"
    assert payload["hitl_causes"]["77"] == "needs triage eyes"


def test_websocket_replays_history_and_streams_live_events(
    dashboard_app: DashboardAppBundle,
) -> None:
    bus = dashboard_app.event_bus
    history_events = [
        EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"}),
        EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "implement"}),
    ]
    _publish_events(bus, *history_events)

    client = TestClient(dashboard_app.app)
    with client.websocket_connect("/ws") as ws:
        first = json.loads(ws.receive_text())
        second = json.loads(ws.receive_text())

        live_event = EventFactory.create(
            type=EventType.WORKER_UPDATE, data={"worker": "implement", "status": "ok"}
        )

        def _send_live() -> None:
            _publish_events(bus, live_event)

        sender = threading.Thread(target=_send_live, daemon=True)
        sender.start()
        live = json.loads(ws.receive_text())
        sender.join(timeout=5)

    assert first["data"]["phase"] == "plan"
    assert second["data"]["phase"] == "implement"
    assert live["type"] == "worker_update"
    assert live["data"]["worker"] == "implement"
