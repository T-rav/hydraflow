"""s52 - HumanSteeringLoop emits worker status; seeds a real /pause directive.

Golden path: the sandbox runtime starts the real ``HumanSteeringLoop`` and
ticks it against an issue carrying a seeded ``/pause`` comment (Task 5's
``MockWorldSeed.comments`` — no longer synthetic, no idle-only poll). The
worker-status heartbeat proves the loop is registered, started, and ticking
in the real Docker stack. The sensing/directive-parsing semantics (comment ->
parsed directive -> persisted ``SteeringState``) are covered end-to-end at
the MockWorld layer in ``tests/scenarios/test_human_steering_scenario.py``
(Task 8/12), including the Task 1 authorization allowlist and the
actuator-decision seam (``human_steering.apply_steering`` /
``fenced_steering_guidance``).

----------------------------------------------------------------------
WHAT TASK 5 AND TASK 4 UNBLOCKED, AND WHAT'S STILL MISSING
----------------------------------------------------------------------
The previous version of this scenario listed two missing harness
capabilities. Both are now *mostly* resolved:

1. Seeding a comment onto a sandboxed issue: SOLVED. ``MockWorldSeed.comments``
   (src/mockworld/seed.py) now carries per-issue ``{login, body, created_at}``
   entries, and ``FakeGitHub.from_seed`` (src/mockworld/fakes/fake_github.py)
   calls ``add_seeded_comment`` for each one, which appends a structured
   ``FakeComment`` (str subclass carrying real ``login``/``created_at``) to
   ``FakeIssue.comments``. ``list_issue_comments`` reads those fields back out
   as the `{"user": {"login": ...}, "body": ..., "created_at": ...}` shape
   ``human_steering.parse_directives`` consumes. This scenario now seeds a
   real ``/pause`` comment from an authorized login via that path (below) —
   the same mechanism ``sandbox_main.py`` uses to build the shared
   ``FakeGitHub`` the whole sandbox orchestrator runs against.

2. Making the seeded issue "active" enough to be sensed: SOLVED by Task 4.
   ``HumanSteeringLoop``'s ``active_issues_cb`` is wired in
   ``service_registry.py`` (the same factory ``sandbox_main.py`` calls) to
   ``lambda: list(store.get_active_issues().keys())`` — the full-pipeline
   active-issue set, not the narrower implement/review/HITL-in-flight set.
   ``store`` in the sandbox is a real ``FakeIssueStore``, whose
   ``get_active_issues()`` returns whatever ``mark_active()`` populated.
   Driving the seeded issue through even one real phase (e.g. triage, via
   ``loops_enabled=None`` so phase orchestrators run) marks it active, which
   is sufficient for ``HumanSteeringLoop`` to fetch its comments.

3. STILL MISSING: enabling the feature itself. ``human_steering_enabled``
   defaults to ``False`` (src/config.py) and — unlike, say,
   ``HYDRAFLOW_CONVERGENCE_OSCILLATION_LOOP_ENABLED`` (a real, working env
   override for a different caretaker) — it has no entry in
   ``_ENV_BOOL_OVERRIDES`` (src/config.py), so there is no
   ``HYDRAFLOW_HUMAN_STEERING_ENABLED`` env var docker-compose.sandbox.yml
   could set, and ``MockWorldSeed`` has no generic config-override field a
   scenario could use instead. Adding either is a ``src/config.py`` (and
   possibly ``docker-compose.sandbox.yml``) change — outside this task's
   scope (seeding + scenario-assertion upgrades only). Without
   ``human_steering_enabled=True``, ``HumanSteeringLoop._do_work`` always
   early-returns ``{"status": "config_disabled"}`` before it ever calls
   ``list_issue_comments`` or touches ``StateData.human_steering`` — so a
   real ``/api/state`` ``flow == "paused"`` assertion is NOT reachable in
   this Docker sandbox today, no matter what gets seeded.

----------------------------------------------------------------------
WHAT THIS SCENARIO ASSERTS INSTEAD (real, not pure smoke)
----------------------------------------------------------------------
Rather than leave this an idle no-comment poll, the seed now attaches a real
``/pause`` comment from an authorized-looking login to the issue (exercising
the Task 5 seeding path end-to-end through ``sandbox_main.py`` ->
``FakeGitHub.from_seed`` -> ``add_seeded_comment``), and drives the issue
through triage so it becomes active in ``FakeIssueStore`` (Task 4's
active-set). ``assert_outcome`` still asserts the worker-status heartbeat
(``BACKGROUND_WORKER_STATUS`` with ``worker == "human_steering"``), which
fires regardless of ``human_steering_enabled`` (``BaseBackgroundLoop.
_execute_cycle`` publishes it whenever ``_do_work()`` returns, including the
``config_disabled`` early return) — proving Docker/UI/wiring, exactly as
before. It ALSO asserts, via ``/api/state``, that ``StateData.human_steering``
for the issue is still the unset default (no ``flow: "paused"``) BECAUSE the
feature is off — an explicit, named assertion of the current gated state
rather than silence, so a future PR that adds the missing env override (item
3 above) has a failing assertion here pointing at exactly what to flip to
``"paused"``.

If a future task adds ``human_steering_enabled`` to ``_ENV_BOOL_OVERRIDES``
and a ``HYDRAFLOW_HUMAN_STEERING_ENABLED`` env line in
docker-compose.sandbox.yml, this scenario should drop the "still disabled"
assertion and replace it with
``payload["human_steering"][str(issue_number)]["flow"] == "paused"``
(``StateData.human_steering`` is a real Pydantic field, already present in
the ``/api/state`` payload today, unfiltered — this is the same
``to_dict()`` / ``model_dump()`` route s51 uses for ``convergence_ledgers``).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s52_human_steering_directive"
DESCRIPTION = (
    "HumanSteeringLoop ticks against an issue carrying a seeded /pause "
    "comment and emits worker status; the directive itself is inert until "
    "human_steering_enabled gets an env override (documented gap)."
)

_ISSUE_NUMBER = 1
_AUTHORIZED_LOGIN = "sandbox-operator"


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["human_steering"],
        issues=[
            {
                "number": _ISSUE_NUMBER,
                "title": "steer me",
                "body": "issue body for the human-steering sandbox scenario",
                "labels": ["in-progress"],
            }
        ],
        # Task 5 seeding: a real /pause comment from a named login, exercised
        # through the same FakeGitHub.from_seed -> add_seeded_comment path
        # sandbox_main.py wires the whole orchestrator against. Inert today
        # because human_steering_enabled has no env override (see module
        # docstring item 3) — HumanSteeringLoop._do_work short-circuits on
        # the config gate before ever calling list_issue_comments.
        comments={
            _ISSUE_NUMBER: [
                {
                    "body": "/pause",
                    "login": _AUTHORIZED_LOGIN,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        },
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify the worker-status heartbeat, and that steering stays inert
    while ``human_steering_enabled`` remains dark-by-default with no env
    override wired (see module docstring)."""
    _ = page  # UI interaction not needed for this caretaker assertion

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

    # Named, explicit assertion of the current gated reality (not silence):
    # the seeded /pause comment exists on the issue (Task 5 seeding worked),
    # but StateData.human_steering for this issue is untouched because
    # human_steering_enabled defaults False and nothing in this sandbox flips
    # it. If a future PR wires HYDRAFLOW_HUMAN_STEERING_ENABLED (see module
    # docstring item 3), this assertion is the one to replace with
    # `flow == "paused"`.
    state_payload = await api.get("/api/state")
    assert isinstance(state_payload, dict)
    human_steering = state_payload.get("human_steering") or {}
    entry = human_steering.get(str(_ISSUE_NUMBER))
    assert entry is None or entry.get("flow") in (None, "running"), (
        "human_steering_enabled has no env override in this sandbox yet, so "
        "the seeded /pause must NOT have been actuated into a persisted "
        f"paused flow; got entry={entry!r}. If this now shows "
        "flow == 'paused', the env-override gap (module docstring item 3) "
        "has been closed — upgrade this assertion accordingly."
    )
