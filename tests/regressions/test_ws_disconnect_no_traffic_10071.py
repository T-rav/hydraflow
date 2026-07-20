"""Regression #10071: /ws handlers must end when the client disconnects with
zero events flowing.

Both dashboard WebSocket paths streamed with a bare ``await queue.get()`` loop
and never called ``receive()``, so a handler whose client vanished on a quiet
bus parked forever: no event ever arrived, no send ever failed. Every closed
browser tab leaked one bus subscription plus one ASGI task, and in-process
harnesses (the browser scenarios) then wedged at event-loop close — the
orphaned task survives ``stop_dashboard`` and uvicorn's ``run_asgi`` swallows
the loop-close ``CancelledError`` (``except BaseException``) before awaiting
an event nobody sets, hanging pytest until the CI job timeout.

These pins drive the real endpoint with a server-push-only fake client and
assert the handler RETURNS (is not cancelled) once the client goes away.
"""

from __future__ import annotations

import asyncio
from typing import Any

from events import EventBus, EventType
from tests.conftest import EventFactory
from tests.helpers import find_endpoint, make_dashboard_router


class _ServerPushClient:
    """Starlette-WebSocket stand-in for the dashboard's push-only client."""

    def __init__(self) -> None:
        self.query_params: dict[str, str] = {}
        self.accepted = False
        self.sent: list[str] = []
        self._frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def receive(self) -> dict[str, Any]:
        return await self._frames.get()

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass

    def client_sends(self, text: str) -> None:
        self._frames.put_nowait({"type": "websocket.receive", "text": text})

    def client_disconnects(self) -> None:
        self._frames.put_nowait({"type": "websocket.disconnect", "code": 1001})


async def _drain_until(predicate, timeout: float = 5.0) -> None:
    """Poll *predicate* until true (bounded), yielding to the loop."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition never held"
        await asyncio.sleep(0.01)


def _ws_endpoint(config, event_bus, state, tmp_path):
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    endpoint = find_endpoint(router, "/ws")
    assert endpoint is not None
    return endpoint


async def test_ws_handler_returns_on_disconnect_without_any_traffic(
    config, event_bus: EventBus, state, tmp_path
) -> None:
    # The exact #10071 shape: connected, zero events flowing, client vanishes.
    # The old code parked on queue.get() forever here (wait_for would time out).
    endpoint = _ws_endpoint(config, event_bus, state, tmp_path)
    client = _ServerPushClient()

    task = asyncio.create_task(endpoint(client))
    await _drain_until(lambda: event_bus._subscribers)

    client.client_disconnects()
    await asyncio.wait_for(task, timeout=5)

    assert not task.cancelled(), "handler must END on disconnect, not need a cancel"
    assert event_bus._subscribers == [], "bus subscription leaked after disconnect"


async def test_ws_handler_ignores_stray_client_frames_but_ends_on_disconnect(
    config, event_bus: EventBus, state, tmp_path
) -> None:
    # A stray client frame (nothing in the dashboard sends one) must not end
    # the stream; the following disconnect must.
    endpoint = _ws_endpoint(config, event_bus, state, tmp_path)
    client = _ServerPushClient()

    task = asyncio.create_task(endpoint(client))
    await _drain_until(lambda: event_bus._subscribers)

    client.client_sends("ping")
    await event_bus.publish(
        EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
    )
    await _drain_until(lambda: client.sent)  # stream still live after the frame

    client.client_disconnects()
    await asyncio.wait_for(task, timeout=5)

    assert any('"phase_change"' in msg or "phase_change" in msg for msg in client.sent)


async def test_merged_ws_returns_on_disconnect_without_any_traffic(
    config, event_bus: EventBus, state, tmp_path
) -> None:
    # Same pin for the multi-repo ``repo=__all__`` fan-in path.
    from dashboard_routes._routes import _serve_merged_ws

    client = _ServerPushClient()
    runtimes = [(config, state, event_bus, lambda: None, "repo-a")]

    task = asyncio.create_task(_serve_merged_ws(client, runtimes))
    await _drain_until(lambda: event_bus._subscribers)

    client.client_disconnects()
    await asyncio.wait_for(task, timeout=5)

    assert not task.cancelled()
    assert event_bus._subscribers == [], "merged path leaked its bus subscription"
