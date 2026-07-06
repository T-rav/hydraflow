"""s52 — HumanSteeringLoop: seeded /pause directive actuates to flow=paused.

This scenario exercises the real ``HumanSteeringLoop`` caretaker (ADR-0099
surface #4) end-to-end inside the docker sandbox. It seeds a real ``/pause``
comment (via ``MockWorldSeed.comments`` — see ``FakeGitHub.from_seed`` ->
``add_seeded_comment``) from a login that is explicitly allow-listed via
``HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS`` (docker-compose.sandbox.yml),
drives the issue through the real pipeline so it becomes "active" in
``FakeIssueStore`` (the set ``HumanSteeringLoop``'s ``active_issues_cb``
reads), and asserts via ``/api/state`` that the persisted
``StateData.human_steering`` entry for the issue shows ``flow == "paused"``.

The sensing/directive-parsing semantics (comment -> parsed directive ->
persisted ``SteeringState``, the Task 1 authorization allowlist, and the
actuator-decision seam ``human_steering.apply_steering`` /
``fenced_steering_guidance``) are covered end-to-end at the MockWorld layer
in ``tests/scenarios/test_human_steering_scenario.py``. This scenario's job
is narrower and complementary: prove the real caretaker, running inside the
real Docker orchestrator against the real dashboard API, actually persists
that outcome where an operator (or CI) can observe it.

----------------------------------------------------------------------
WHY THE ISSUE NEEDS TO BE "ACTIVE" WHEN THE LOOP TICKS (not just once)
----------------------------------------------------------------------
``HumanSteeringLoop._do_work`` snapshots ``active_issues_cb()`` once per
tick (every 60 s in the sandbox — ``WorkerRegistryCallbacks(get_interval=
lambda *_: 60)`` overrides every caretaker's interval, per s51's precedent).
``active_issues_cb`` is wired in ``service_registry.py`` to
``lambda: list(store.get_active_issues().keys())`` — the ``FakeIssueStore``
active set that ``store_lifecycle`` (``phase_utils.py``) populates via
``mark_active`` on phase entry and clears via ``mark_complete`` on phase
exit. A phase that completes instantly (the Fakes have no artificial
latency) holds that window open for a single event-loop tick — far too
narrow to reliably coincide with a 60-second caretaker cadence if the issue
is only driven through the pipeline once.

s51 (``s51_convergence_oscillation.py``) solves the identical timing problem
for ``ConvergenceOscillationLoop`` by driving the issue into a state where a
phase orchestrator's ``_polling_loop`` (``orchestrator.py``) keeps
re-entering ``store_lifecycle`` in a tight loop with no sleep between
iterations: ``_polling_loop`` only sleeps ``poll_interval`` when
``did_work`` is falsy (``if did_work: continue`` — no sleep). Scripting plan
to fail (``{"success": False}``) makes ``plan_issues()`` keep returning a
non-empty (truthy) result every iteration — PlanPhase records the failure,
skips the label swap (the issue stays on ``hydraflow-plan``), and the plan
loop immediately re-polls and reprocesses the same issue, over and over,
for the lifetime of the scenario run. That keeps the issue flickering
active/inactive at effectively the event-loop's own cadence rather than
once every ``poll_interval`` (30 s default), so ``HumanSteeringLoop``'s
60-second tick has continuous opportunities to observe it as active over
the scenario's run.

This scenario reuses that same "plan fails forever" vehicle, simplified to
skip the discover/shape detour s51 needs for its oscillation ledger (not
relevant here): triage scripts ``ready=True`` (default ``clarity_score=10``
clears the discovery gate) so the issue routes straight from
``hydraflow-find`` to ``hydraflow-plan`` in one triage pass, then plan fails
forever. This also keeps the Tier-1 in-process parity check
(``test_sandbox_parity.py``, which for ``loops_enabled=None`` runs a
*single-shot* ``MockWorld.run_pipeline()`` — triage once, then plan once,
no repeated cycling) satisfied: it asserts the issue's ``final_stage !=
"triage"``, which requires the seed's single-shot outcome be a plan result,
not merely a ``discover``-routed issue that ``run_pipeline`` never revisits.

----------------------------------------------------------------------
ALLOWLIST-FROM-ENV
----------------------------------------------------------------------
``human_steering_authorized_users`` defaults to ``[]`` (honors nobody, safe
default-on for ``human_steering_enabled``). ``HYDRAFLOW_HUMAN_STEERING_
AUTHORIZED_USERS`` (comma-separated, special-cased in
``_apply_env_overrides`` the same way ``HYDRAFLOW_LITE_PLAN_LABELS``
populates ``lite_plan_labels``) is set to ``"steer-bot"`` in
docker-compose.sandbox.yml. ``_AUTHORIZED_LOGIN`` below MUST match that
value — this scenario seeds its ``/pause`` comment from that exact login so
the sensor's allowlist check (``human_steering.parse_directives``) actually
honors it.

----------------------------------------------------------------------
WHAT THIS SCENARIO ASSERTS
----------------------------------------------------------------------
Via ``/api/state``: ``StateData.human_steering[str(issue_number)].flow ==
"paused"`` — the real caretaker loop parsed the seeded ``/pause`` comment
from the allow-listed login and persisted the paused flow, unfiltered,
exactly as ``StateData`` (a real Pydantic field) serializes it
(``to_dict()`` / ``model_dump()`` — the same route s51 uses for
``convergence_ledgers``). This is the terminal proof for ADR-0103's
human-steering directive path: Docker + real config gate + real allowlist
+ real sensor loop + real dashboard API, not a MockWorld-layer unit
assertion.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s52_human_steering_directive"
DESCRIPTION = (
    "Seeded /pause from an allow-listed login actuates through the real "
    "HumanSteeringLoop; /api/state shows the issue's human_steering "
    "flow == 'paused'."
)

_ISSUE_NUMBER = 1
_AUTHORIZED_LOGIN = "steer-bot"  # MUST match docker-compose.sandbox.yml's
# HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS value.


def seed() -> MockWorldSeed:
    """Seed a /pause comment from the allow-listed login and keep the issue
    perpetually active via the "plan fails forever" tight-loop recipe (see
    module docstring) so HumanSteeringLoop's 60-second tick has continuous
    opportunities to observe the issue as active.
    """
    return MockWorldSeed(
        # loops_enabled=None: all caretaker loops run (including
        # human_steering — gated off unless human_steering_enabled, which
        # is default-on) AND phase orchestrators run regardless (they use a
        # separate BGWorkerManager gate — see s51's
        # _build_caretaker_enabled_cb docstring). Required so triage/plan
        # actually process the issue and mark_active/mark_complete populate
        # FakeIssueStore.get_active_issues().
        loops_enabled=None,
        issues=[
            {
                "number": _ISSUE_NUMBER,
                "title": "Investigate recurring churn in auth module",
                "body": (
                    "The auth module changes have been cycling through "
                    "planning without converging."
                ),
                "labels": ["hydraflow-find"],
            }
        ],
        # A real /pause comment from the allow-listed login, seeded through
        # the same FakeGitHub.from_seed -> add_seeded_comment path
        # sandbox_main.py wires the whole orchestrator against.
        comments={
            _ISSUE_NUMBER: [
                {
                    "body": "/pause",
                    "login": _AUTHORIZED_LOGIN,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        },
        scripts={
            # ready=True (default clarity_score=10 clears the discovery
            # gate) routes the issue straight from hydraflow-find to
            # hydraflow-plan in one triage pass (no discover/shape detour —
            # keeps the Tier-1 single-shot run_pipeline() parity check
            # satisfied; see module docstring).
            "triage": {_ISSUE_NUMBER: [{"ready": True}]},
            # Plan fails forever: PlanPhase sets ts_status="failed", skips
            # the label swap (issue stays on hydraflow-plan), and the plan
            # polling loop immediately re-polls (did_work is truthy) with no
            # sleep — see module docstring. This is what keeps the issue
            # perpetually active for HumanSteeringLoop to observe. FakeLLM's
            # last-scripted-entry-repeats semantics mean this single
            # {"success": False} entry keeps being returned indefinitely.
            "plan": {_ISSUE_NUMBER: [{"success": False}]},
        },
        # cycles_to_run is used by the Tier-1 in-process parity test
        # (test_sandbox_parity.py). With loops_enabled=None that harness
        # runs MockWorld.run_pipeline() (single-shot phase orchestration,
        # not the background-loop path) and only asserts generic pipeline
        # progress — it does not exercise HumanSteeringLoop's tick timing,
        # which is Docker-only (Tier 2). The Tier-2 Docker sandbox runs
        # until assert_outcome's polling timeout, giving the caretaker's
        # 60-second tick ample opportunity against the continuously-active
        # issue.
        cycles_to_run=16,
    )


async def assert_outcome(api, page) -> None:
    """Assert HumanSteeringLoop actuated the seeded /pause into a persisted
    paused flow, visible via /api/state.

    Polls with a generous 120-second timeout so the 60-second caretaker
    tick (sandbox interval_cb override) has time to land while the issue is
    active (the plan-failure tight loop keeps re-opening that window — see
    module docstring) and the state write to propagate through the
    StateTracker before the deadline.
    """
    _ = page  # UI interaction not needed for this caretaker assertion

    def _paused(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        human_steering = payload.get("human_steering")
        if not isinstance(human_steering, dict):
            return False
        entry = human_steering.get(str(_ISSUE_NUMBER))
        return isinstance(entry, dict) and entry.get("flow") == "paused"

    state_payload = await api.wait_until(
        "/api/state",
        _paused,
        timeout=120.0,
    )

    human_steering = state_payload.get("human_steering") or {}
    entry = human_steering.get(str(_ISSUE_NUMBER))
    assert isinstance(entry, dict), (
        f"expected a human_steering entry for issue #{_ISSUE_NUMBER}; "
        f"got human_steering={human_steering!r}"
    )
    assert entry.get("flow") == "paused", (
        "HumanSteeringLoop should have parsed the seeded /pause comment "
        f"from the allow-listed login {_AUTHORIZED_LOGIN!r} and persisted "
        f"flow == 'paused'; got entry={entry!r}"
    )
