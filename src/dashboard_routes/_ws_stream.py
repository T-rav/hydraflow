"""Real-time WebSocket event streaming for the dashboard.

The dashboard's ``/ws`` feeds are server-push only: a handler replays event
history, then pumps live bus events to the socket until the client goes away.
This module owns that streaming layer — disconnect classification, the
client-gone watcher, the queue→socket pump, and the merged ``repo=__all__``
fan-in that stamps and interleaves every runtime's bus into one feed.

Extracted verbatim from ``dashboard_routes._routes`` (god-file decomposition).
``_routes`` re-exports every name here, so existing imports such as
``from dashboard_routes._routes import _serve_merged_ws`` keep working
unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from events import HydraFlowEvent

logger = logging.getLogger("hydraflow.dashboard")


def _is_likely_disconnect(exc: BaseException) -> bool:
    """Return True if *exc* looks like a normal WebSocket disconnect rather than a code bug."""
    disconnect_types = (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
    )
    if isinstance(exc, disconnect_types):
        return True
    name = type(exc).__name__
    # Starlette / uvicorn raise these on unclean disconnects.
    return name in {
        "WebSocketDisconnect",
        "ConnectionClosedError",
        "ConnectionClosedOK",
    }


async def _client_gone(ws: WebSocket) -> None:
    """Resolve once the WebSocket client has gone away.

    The dashboard's ``/ws`` feeds are server-push only — a healthy client never
    sends frames — so the streaming loop parks on ``queue.get()``. Without a
    concurrent ``receive()`` the handler can never observe a vanished client on
    a quiet bus: no events flow, so no send ever fails, and the ASGI task sits
    on ``queue.get()`` forever. That leaks the bus subscription for every
    closed browser tab, and in-process harnesses (browser scenarios) then
    wedge at event-loop close: the orphaned handler survives shutdown, and
    uvicorn's ``run_asgi`` swallows the loop-close ``CancelledError``
    (``except BaseException``) before awaiting an event nobody will ever set
    (#10071).

    Stray client frames are drained and ignored; any receive failure is
    treated as "client gone" (fail-closed — a live client would reconnect,
    while the alternative is a permanent leak). ``CancelledError`` is never
    swallowed here.

    The loop continues ONLY for a genuine client data frame
    (``{"type": "websocket.receive"}``); anything else — disconnect, a
    non-dict, an unknown type — returns immediately. Post-accept, real
    Starlette only ever yields ``websocket.receive`` / ``websocket.disconnect``
    dicts, so production behavior is unchanged; the guard exists because a
    stubbed socket (``AsyncMock``) resolves ``receive()`` instantly with a
    ``Mock``, and an unguarded loop then spins without ever suspending —
    unbounded CPU plus unbounded mock call history (OOM-killed CI runners).
    """
    with contextlib.suppress(Exception):
        while True:
            message = await ws.receive()
            if not isinstance(message, dict):
                return
            if message.get("type") != "websocket.receive":
                return


async def _stream_queue_to_ws(
    ws: WebSocket, queue: asyncio.Queue[HydraFlowEvent]
) -> None:
    """Forward live *queue* events to *ws* until the client disconnects.

    Races ``queue.get()`` against a disconnect watcher (``_client_gone``) so a
    closed tab ends the handler promptly even when no events are flowing.
    Returns on disconnect; send errors propagate to the caller's
    disconnect-aware ``except`` blocks unchanged.

    Cleanup awaits each child task individually rather than via
    ``asyncio.gather``: a ``GatheringFuture`` whose members already finished
    refuses cancellation (``cancel()`` returns ``False``), which corrupts the
    cancellation bookkeeping that anyio's TestClient cancel-scope relies on to
    absorb its own cancel. Both children cancel instantly (bare ``get`` /
    ``receive`` awaits), so the per-task awaits are bounded; a pending outer
    cancellation still propagates after the ``finally`` completes.
    """
    watcher = asyncio.create_task(_client_gone(ws))
    getter: asyncio.Task[HydraFlowEvent] | None = None
    try:
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {watcher, getter}, return_when=asyncio.FIRST_COMPLETED
            )
            if watcher in done:
                return
            event = getter.result()
            getter = None
            await ws.send_text(event.model_dump_json())
    finally:
        for task in (watcher, getter):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


# Per-bus subscriber queue depth; the merged ``repo=__all__`` socket sizes its
# shared fan-in queue at ``N × this`` so a busy line can't starve the others.
_WS_MERGED_PER_BUS_QUEUE = 500

# A resolve_runtimes 5-tuple: (config, state, event_bus, get_orch, slug).
_Runtime = tuple[Any, Any, Any, Callable[[], Any], str]


def _merge_sorted_history(runtimes: list[_Runtime]) -> list[HydraFlowEvent]:
    """Merge every runtime's event history into one ``(timestamp, id)``-sorted list.

    Each event is stamped with its bus's repo slug when it isn't already tagged
    (``set_repo`` tags live events, but legacy/untagged history is normalized
    here). A bus that fails to yield history (a down/unstarted repo) is skipped —
    a single bad line must never sink the merged backfill. The id is the tie
    breaker because the module-global ``_event_counter`` only approximates
    wall-clock order across buses.
    """
    events: list[HydraFlowEvent] = []
    for _cfg, _state, bus, _get_orch, slug in runtimes:
        try:
            history = bus.get_history()
        except Exception:  # noqa: BLE001 — a down repo must not sink the merge
            logger.warning("merged WS: skipping history for repo %s", slug)
            continue
        for event in history:
            events.append(
                event
                if event.repo is not None
                else event.model_copy(update={"repo": slug})
            )
    events.sort(key=lambda e: (e.timestamp, e.id))
    return events


async def _forward_to_merged(
    src: asyncio.Queue[HydraFlowEvent],
    dst: asyncio.Queue[HydraFlowEvent],
    slug: str,
) -> None:
    """Forward live frames from one bus's queue into the shared merged queue.

    Stamps the repo slug when missing and drops the oldest frame on a full
    shared queue (mirroring ``EventBus.publish``'s slow-subscriber policy) so a
    single repo can't block the fan-in. Cancelled when the socket closes.
    """
    while True:
        event = await src.get()
        if event.repo is None:
            event = event.model_copy(update={"repo": slug})
        try:
            dst.put_nowait(event)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                dst.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                dst.put_nowait(event)


async def _serve_merged_ws(ws: WebSocket, runtimes: list[_Runtime]) -> None:
    """Stream a merged, repo-tagged event feed across every runtime's bus.

    Sends a ``(timestamp, id)``-sorted history backfill, then fans every bus's
    live subscription into one shared queue. A repo whose subscription fails is
    skipped (never a 1008 close — that would stop the frontend reconnect for the
    whole aggregate view). The single-repo fast path is handled by the caller.

    Note on ordering/dedup: ``event.id`` is unique only within a process'
    *live* stream (one shared counter), but persisted history from independent
    past sessions can reuse ids across repos. The merged feed therefore streams
    every frame repo-tagged and lets the client de-collide on ``(repo, id)`` —
    it never drops a frame here. Timestamps are uniformly UTC ISO-8601, so the
    lexicographic ``(timestamp, id)`` sort is chronological.
    """
    await ws.accept()
    if not runtimes:
        # Degenerate empty-aggregate view (no registered runtimes): close
        # cleanly instead of holding a socket the out-queue can never feed.
        # In practice the empty-registry guard (#9359) yields the default
        # runtime, so this only triggers defensively.
        with contextlib.suppress(Exception):
            await ws.close(code=1000)
        return
    history = _merge_sorted_history(runtimes)
    out_queue: asyncio.Queue[HydraFlowEvent] = asyncio.Queue(
        maxsize=max(1, len(runtimes)) * _WS_MERGED_PER_BUS_QUEUE
    )
    forwarders: list[asyncio.Task[None]] = []
    async with contextlib.AsyncExitStack() as stack:
        for _cfg, _state, bus, _get_orch, slug in runtimes:
            try:
                queue = await stack.enter_async_context(bus.subscription())
            except Exception:  # noqa: BLE001 — skip a down repo, keep the socket
                logger.warning("merged WS: skipping live feed for repo %s", slug)
                continue
            forwarders.append(
                asyncio.create_task(_forward_to_merged(queue, out_queue, slug))
            )
        try:
            for event in history:
                await ws.send_text(event.model_dump_json())
            await _stream_queue_to_ws(ws, out_queue)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            if _is_likely_disconnect(exc):
                logger.warning(
                    "WebSocket disconnect during merged streaming: %s",
                    exc.__class__.__name__,
                )
            else:
                logger.error(
                    "WebSocket error during merged streaming: %s",
                    exc.__class__.__name__,
                    exc_info=True,
                )
        finally:
            # Await the cancellations so the buses are unsubscribed (AsyncExitStack
            # exit) only after their forwarders have actually stopped reading.
            # Per-task awaits, not asyncio.gather: a GatheringFuture whose members
            # already finished refuses cancellation, which corrupts the outer
            # cancel-scope bookkeeping (see _stream_queue_to_ws / #10071).
            for task in forwarders:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
