from arch.extractors.events import extract_event_topology

# A miniature `events.py` mirroring the real fan-out bus shape: a declared
# `EventType` enum plus the live-only `EPHEMERAL_EVENT_TYPES` allowlist.
_EVENTS_STUB = """
from enum import StrEnum


class EventType(StrEnum):
    ALPHA = "alpha"
    BETA = "beta"
    GHOST = "ghost"
    SNAP = "snap"


EPHEMERAL_EVENT_TYPES = frozenset({EventType.SNAP})
"""


def _tree(fixture_src_tree, extra):
    spec = {"src/events.py": _EVENTS_STUB}
    spec.update(extra)
    return fixture_src_tree(spec)


def test_enumerates_all_declared_event_types(fixture_src_tree):
    # Every declared EventType member surfaces, even with no publisher/subscriber.
    root = _tree(fixture_src_tree, {})
    topo = extract_event_topology(root / "src")
    names = {e.event for e in topo.events}
    assert {"ALPHA", "BETA", "GHOST", "SNAP"} <= names


def test_argless_subscription_is_a_global_subscriber(fixture_src_tree):
    root = _tree(
        fixture_src_tree,
        {
            "src/dash.py": """
            class Dashboard:
                async def stream(self, bus):
                    async with bus.subscription() as queue:
                        async for event in queue:
                            yield event
            """,
        },
    )
    topo = extract_event_topology(root / "src")
    assert any("dash" in s and "Dashboard.stream" in s for s in topo.global_subscribers)


def test_argless_subscribe_is_a_global_subscriber(fixture_src_tree):
    root = _tree(
        fixture_src_tree,
        {
            "src/drain.py": """
            class Drain:
                def go(self, bus):
                    queue = bus.subscribe(max_queue=10)
                    return queue
            """,
        },
    )
    topo = extract_event_topology(root / "src")
    assert any("Drain.go" in s for s in topo.global_subscribers)


def test_publisher_makes_event_alive(fixture_src_tree):
    root = _tree(
        fixture_src_tree,
        {
            "src/emitter.py": """
            class Emitter:
                async def go(self, bus):
                    await bus.publish(HydraFlowEvent(type=EventType.ALPHA))
            """,
        },
    )
    topo = extract_event_topology(root / "src")
    edge = {e.event: e for e in topo.events}["ALPHA"]
    assert edge.publishers
    assert edge.ephemeral is False


def test_declared_event_without_publisher_is_publisherless(fixture_src_tree):
    root = _tree(fixture_src_tree, {})
    topo = extract_event_topology(root / "src")
    ghost = {e.event: e for e in topo.events}["GHOST"]
    assert ghost.publishers == []
    assert ghost.ephemeral is False


def test_ephemeral_allowlist_member_marked_ephemeral(fixture_src_tree):
    root = _tree(fixture_src_tree, {})
    topo = extract_event_topology(root / "src")
    snap = {e.event: e for e in topo.events}["SNAP"]
    assert snap.ephemeral is True


def test_internal_self_subscribe_is_not_a_consumer(fixture_src_tree):
    # EventBus.subscription() delegates to self.subscribe(); that internal
    # plumbing must never be counted as a fan-out consumer.
    root = _tree(
        fixture_src_tree,
        {
            "src/bus_impl.py": """
            class EventBus:
                def subscribe(self, max_queue=500):
                    return object()

                def subscription(self):
                    queue = self.subscribe(max_queue=500)
                    return queue
            """,
        },
    )
    topo = extract_event_topology(root / "src")
    assert not any("EventBus.subscription" in s for s in topo.global_subscribers)


def test_phantom_per_type_subscribe_is_not_a_global_subscriber(fixture_src_tree):
    # A subscribe() carrying an EventType arg is the phantom per-type API that
    # the real bus never exposed; it must not register as a fan-out consumer.
    root = _tree(
        fixture_src_tree,
        {
            "src/legacy.py": """
            class Legacy:
                def wire(self, bus):
                    bus.subscribe(EventType.ALPHA, self.on_alpha)
            """,
        },
    )
    topo = extract_event_topology(root / "src")
    assert not any("Legacy.wire" in s for s in topo.global_subscribers)


def test_typed_subscribe_is_a_typed_subscriber_not_fanout(fixture_src_tree):
    # A ``subscribe(types={EventType.X, ...})`` call (ADR-0114) registers as a
    # typed subscriber carrying its filter, NOT as a fan-out consumer.
    root = _tree(
        fixture_src_tree,
        {
            "src/waker.py": """
            class WakeRouter:
                def wire(self, bus):
                    return bus.subscribe(types={EventType.ALPHA, EventType.BETA})
            """,
        },
    )
    topo = extract_event_topology(root / "src")
    typed = {t.subscriber: t.types for t in topo.typed_subscribers}
    match = next((v for k, v in typed.items() if "WakeRouter.wire" in k), None)
    assert match == ["ALPHA", "BETA"]  # sorted EventType members it filters on
    # A typed subscriber must not double as a fan-out consumer.
    assert not any("WakeRouter.wire" in s for s in topo.global_subscribers)


def test_typed_subscription_context_manager_is_recognized(fixture_src_tree):
    root = _tree(
        fixture_src_tree,
        {
            "src/consumer.py": """
            class Consumer:
                async def run(self, bus):
                    async with bus.subscription(types=frozenset({EventType.ALPHA})) as q:
                        async for event in q:
                            yield event
            """,
        },
    )
    topo = extract_event_topology(root / "src")
    typed = {t.subscriber: t.types for t in topo.typed_subscribers}
    match = next((v for k, v in typed.items() if "Consumer.run" in k), None)
    assert match == ["ALPHA"]
    assert not any("Consumer.run" in s for s in topo.global_subscribers)


def test_explicit_types_none_is_still_a_fanout_subscriber(fixture_src_tree):
    # ``subscribe(types=None)`` is an explicit fan-out request, not a typed one.
    root = _tree(
        fixture_src_tree,
        {
            "src/plain.py": """
            class Plain:
                def go(self, bus):
                    return bus.subscribe(types=None)
            """,
        },
    )
    topo = extract_event_topology(root / "src")
    assert any("Plain.go" in s for s in topo.global_subscribers)
    assert not any("Plain.go" in t.subscriber for t in topo.typed_subscribers)


def test_returns_empty_when_no_events(fixture_src_tree):
    root = fixture_src_tree({"src/foo.py": "x = 1"})
    topo = extract_event_topology(root / "src")
    assert topo.events == []
    assert topo.global_subscribers == []
    assert topo.typed_subscribers == []
