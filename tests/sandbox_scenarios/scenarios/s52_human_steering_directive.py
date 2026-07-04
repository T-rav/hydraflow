"""s52 - HumanSteeringLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``HumanSteeringLoop`` and an
idle cycle (no comment/directive wiring, no issue mid-pipeline) completes
without error, proving the loop is registered, started, and heartbeating in
the real Docker stack. This sandbox scenario exists to catch docker/UI/wiring
regressions only; the sensing semantics (comment -> parsed directive ->
persisted ``SteeringState``) are already covered end-to-end by the MockWorld
scenario in ``tests/scenarios/test_human_steering_scenario.py`` (Task 8).

----------------------------------------------------------------------
WHY THIS IS AN IDLE-POLL SMOKE, NOT A REAL DIRECTIVE-PICKUP ASSERTION
----------------------------------------------------------------------
A real "/pause comment -> persisted flow == paused" assertion through the
docker sandbox would require two capabilities the harness does not currently
have:

1. Seeding a GitHub comment onto a sandboxed issue via ``MockWorldSeed``.
   ``MockWorldSeed.issues`` entries only carry ``number``/``title``/``body``/
   ``labels`` (src/mockworld/seed.py); ``FakeGitHub.from_seed`` calls
   ``add_issue(number, title, body, labels)`` (src/mockworld/fakes/
   fake_github.py), which never reads or sets ``FakeIssue.comments``. The
   only runtime path that appends to ``FakeIssue.comments`` is
   ``FakeGitHub.post_comment``, called internally by HITL actuator routes
   (``src/dashboard_routes/_hitl_routes.py``) — there is no dashboard API
   route a Tier-2 ``assert_outcome(api, page)`` can call to post a comment
   onto an issue, and ``assert_outcome`` only receives the HTTP ``api``
   client + Playwright ``page`` (no handle to the sandbox's ``FakeGitHub``
   instance to call ``post_comment`` directly either).

2. Making the seeded issue "active" so ``HumanSteeringLoop._do_work`` calls
   ``list_issue_comments`` on it at all. The loop's ``active_issues_cb`` is
   wired to ``state.get_active_issue_numbers`` in production
   (src/service_registry.py), which is populated exclusively by
   ``HydraFlowOrchestrator._sync_active_issue_numbers`` as the union of the
   implementer/reviewer/HITL-controller active-issue sets (src/
   orchestrator.py). A purely idle/seeded issue that never enters
   implement/review/HITL never appears in that set, so the loop's tick
   would fetch zero comments for it regardless of what got seeded.

Rather than invent a harness capability that does not exist (a seed-level
``comments`` field, or an API route to post one), this scenario mirrors
``s50_disturbance_dampener_idle_poll``'s shape exactly: assert the loop is
registered, started, and ticks without error inside the real Docker stack.
``HumanSteeringLoop`` inherits ``BaseBackgroundLoop._execute_cycle``, which
publishes a ``BACKGROUND_WORKER_STATUS`` event with ``status="ok"`` whenever
``_do_work()`` returns normally — this holds even when ``_do_work`` early-
returns ``{"status": "config_disabled"}`` (``human_steering_enabled``
defaults to ``False`` and there is no ``HYDRAFLOW_HUMAN_STEERING_ENABLED``
env override in ``docker-compose.sandbox.yml`` today), so the event fires
regardless of the config gate and proves the wiring — not the directive
semantics — end-to-end in Docker.

If a future task adds seed-level comment support and an
``HYDRAFLOW_HUMAN_STEERING_ENABLED`` env override plus a way to drive an
issue into "active" state without a full pipeline run, this scenario should
be upgraded to seed a ``/pause`` comment and assert
``payload["human_steering"][str(issue_number)]["flow"] == "paused"`` via
``/api/state`` (the same ``to_dict()`` / ``model_dump()`` route s51 uses for
``convergence_ledgers`` — ``StateData.human_steering`` is a real Pydantic
field so it is already present in that payload today, unfiltered).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s52_human_steering_directive"
DESCRIPTION = "HumanSteeringLoop performs an idle poll and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["human_steering"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by human_steering."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "human_steering"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "human_steering"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one human_steering worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
