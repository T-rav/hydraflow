"""Regression test for issue #10619.

Bug: the event-bus arch extractor (``src/arch/extractors/events.py``) scanned for
a per-``EventType`` ``subscribe(EventType.X, ...)`` call that HydraFlow's
``EventBus`` never exposed. ``subscribe()`` / ``subscription()`` take *no* event
type — they return a queue that receives *every* published event (fan-out). The
one real consumer is the dashboard WebSocket endpoint
(``src/dashboard_routes/_routes.py``), which drains all events and streams them
to the UI. Because the extractor's per-type target pattern never occurred, it
found zero subscribers for every event, so the generator stamped ⚠️
"likely dead" on all ~46 published events — a 100% false artifact.

After the fix:
  - an argless ``subscribe()`` / ``subscription()`` call site registers as a
    GLOBAL subscriber (a fan-out consumer of every published event);
  - an event is "dead" only if it is a declared ``EventType`` with no publisher
    (excluding the live-only ``EPHEMERAL_EVENT_TYPES`` allowlist);
  - therefore NO event that has a publisher is ever flagged dead, and the
    dashboard WebSocket endpoint shows up as a fan-out consumer.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from arch.extractors.events import extract_event_topology  # noqa: E402
from arch.generators.event_bus import render_event_bus  # noqa: E402

_SRC = _REPO / "src"


def test_published_events_are_not_flagged_dead_and_have_a_fanout_consumer():
    topo = extract_event_topology(_SRC)
    md = render_event_bus(topo)

    # The dashboard WebSocket endpoint drains the whole bus — it must be
    # recognized as a global (fan-out) subscriber.
    assert topo.global_subscribers, "expected at least one fan-out consumer"
    assert any("websocket" in s.lower() for s in topo.global_subscribers), (
        f"dashboard /ws consumer missing from {topo.global_subscribers}"
    )

    # The exact bug: every published event was flagged dead. Invert it — no
    # event that has a publisher may carry the ⚠️ dead flag.
    published = [e for e in topo.events if e.publishers]
    assert published, "expected published events in the live tree"
    falsely_dead = [e.event for e in published if f"**{e.event}** ⚠️" in md]
    assert not falsely_dead, f"published events falsely flagged dead: {falsely_dead}"


def test_dead_flag_is_reserved_for_declared_events_without_publisher():
    topo = extract_event_topology(_SRC)
    md = render_event_bus(topo)

    # An event is dead iff declared, unpublished, and not on the ephemeral
    # allowlist. Whatever the extractor classifies as dead must render with the
    # flag; nothing else may.
    for edge in topo.events:
        is_dead = not edge.publishers and not edge.ephemeral
        flagged = f"**{edge.event}** ⚠️" in md
        assert flagged == is_dead, (
            f"{edge.event}: flagged={flagged} but is_dead={is_dead}"
        )
