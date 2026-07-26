from arch._models import EventBusTopology, EventEdge
from arch.generators.event_bus import render_event_bus


def test_live_event_shows_fanout_and_is_not_flagged_dead():
    topo = EventBusTopology(
        events=[
            EventEdge(
                event="PR_CREATED",
                publishers=["src.pr_manager:PRManager.create_pr"],
            )
        ],
        global_subscribers=[
            "src.dashboard_routes._routes:create_router.websocket_endpoint"
        ],
    )
    md = render_event_bus(topo)
    assert "PR_CREATED" in md
    # A published event is never dead — no ⚠️ on its row.
    assert "**PR_CREATED** ⚠️" not in md
    # Fan-out attribution present, and the consumer call-site is listed.
    assert "★" in md
    assert "websocket_endpoint" in md


def test_declared_event_without_publisher_is_flagged_dead():
    topo = EventBusTopology(
        events=[EventEdge(event="GHOST", publishers=[])],
        global_subscribers=["src.dash:consumer"],
    )
    md = render_event_bus(topo)
    assert "**GHOST** ⚠️" in md


def test_ephemeral_event_without_publisher_is_not_flagged_dead():
    topo = EventBusTopology(
        events=[EventEdge(event="PIPELINE_SNAPSHOT", publishers=[], ephemeral=True)],
        global_subscribers=["src.dash:consumer"],
    )
    md = render_event_bus(topo)
    assert "**PIPELINE_SNAPSHOT** ⚠️" not in md


def test_handles_empty_topology():
    md = render_event_bus(EventBusTopology())
    assert "no events" in md.lower()
