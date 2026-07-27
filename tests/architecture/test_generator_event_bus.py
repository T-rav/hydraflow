from arch._models import EventBusTopology, EventEdge, TypedSubscriber
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


def test_typed_subscriber_is_listed_and_attributed_to_its_events():
    topo = EventBusTopology(
        events=[
            EventEdge(
                event="PR_CREATED",
                publishers=["src.pr_manager:PRManager.create_pr"],
            ),
            EventEdge(
                event="TRANSCRIPT_LINE",
                publishers=["src.runner_utils:_stream_and_collect"],
            ),
        ],
        global_subscribers=["src.dashboard_routes._routes:websocket_endpoint"],
        typed_subscribers=[
            TypedSubscriber(
                subscriber="src.wake_router:WakeRouter.wire", types=["PR_CREATED"]
            )
        ],
    )
    md = render_event_bus(topo)
    # The typed consumer is listed in the preamble with its filter...
    assert "Typed consumers" in md
    assert "WakeRouter.wire" in md
    # ...and attributed in the Subscribers column of the event it filters on,
    # alongside the fan-out marker — but NOT on events it does not subscribe to.
    pr_row = next(line for line in md.splitlines() if "**PR_CREATED**" in line)
    transcript_row = next(
        line for line in md.splitlines() if "**TRANSCRIPT_LINE**" in line
    )
    assert "WakeRouter.wire" in pr_row
    assert "★" in pr_row
    assert "WakeRouter.wire" not in transcript_row


def test_no_typed_consumers_block_when_none_present():
    topo = EventBusTopology(
        events=[EventEdge(event="PR_CREATED", publishers=["src.x:y"])],
        global_subscribers=["src.dash:consumer"],
    )
    md = render_event_bus(topo)
    assert "Typed consumers" not in md


def test_handles_empty_topology():
    md = render_event_bus(EventBusTopology())
    assert "no events" in md.lower()
