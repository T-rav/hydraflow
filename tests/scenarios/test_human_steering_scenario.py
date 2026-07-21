"""MockWorld scenario for `HumanSteeringLoop` (ADR-0099 #4, Task 8/12).

Task 5 added structured comment seeding to the real ``FakeGitHub``:
``FakeComment`` (a ``str`` subclass carrying its own ``login``/``created_at``)
plus ``FakeGitHub.add_seeded_comment(issue_number, body, *, login=,
created_at=)``. ``list_issue_comments`` now reads those structured fields
directly instead of hardcoding a single timestamp/author for every seeded
comment. That retires the old ``_TimestampedCommentsGitHub`` delegating
wrapper this module used to define — the real ``FakeGitHub`` can vary author
and timestamp per comment now, so scenarios seed through it directly.

This scenario exercises the sensing path end-to-end: a seeded sequence of
GitHub-comment directives ticked through the real ``HumanSteeringLoop._do_work``
and a real (non-mock) per-issue ``SteeringState`` store, proving:

1. The persisted state after each tick matches
   ``human_steering.parse_directives`` semantics wired through the loop
   rather than asserted against the pure function directly.
2. The Task 1 authorization allowlist is enforced end-to-end through the
   loop: a directive from a login NOT in
   ``config.human_steering_authorized_users`` is sensed and silently
   dropped — no state change results, mirroring "honor nobody" being the
   safe default for an unrecognized author.
3. Actuator effects that follow from what the sensor persisted: the pure
   decision function ``human_steering.apply_steering`` (which
   ``HydraFlowOrchestrator._apply_human_steering`` enacts verbatim — see
   deviation note below) is exercised against the loop's real persisted
   output to prove `/pause` -> skip, `/redo <phase>` -> re-enqueue decision,
   and `/steer` -> guidance that reaches the fenced prompt helper
   (``human_steering.fenced_steering_guidance``, the ADR-0092 single fence
   choke point) all follow correctly from what the sensor actually wrote,
   not from hand-built ``SteeringState`` fixtures.

Harness note / deviation from the brief: the brief's actuator-effects ask
("/pause -> the issue is skipped by the actuator; /redo <phase> ->
re-enqueued; /steer -> the fenced guidance section appears in a built
prompt") describes ``HydraFlowOrchestrator._apply_human_steering``, which is
not reachable through the scenario catalog: ``LoopCatalog.instantiate``
returns a bare ``BaseBackgroundLoop`` (no orchestrator), and constructing a
real ``HydraFlowOrchestrator`` builds its *entire* production service
registry (~50 background loops via ``build_services``) unless a fake
``ServiceRegistry`` is substituted — a scope well beyond a loop-scenario
harness, and not what ``MockWorld`` composes. ``tests/
test_orchestrator_human_steering.py`` already covers the actuator directly
(pause/abort/redo enactment, idempotent-abort guard, fenced-prompt fold)
against a real ``HydraFlowOrchestrator`` with ``store``/``prs`` swapped for
lambdas — this scenario does not duplicate that coverage.

Instead, this scenario proves the seam the brief cares about — "the
actuator's decision follows from what the sensor persisted" — by feeding the
loop's real, sensed ``SteeringState`` (not a hand-built fixture) into the
same pure functions the orchestrator calls verbatim
(``apply_steering``, ``fenced_steering_guidance``), and asserting their
outputs: ``decision.skip`` for `/pause`, ``decision.redo_phase`` for
`/redo <phase>`, and the fenced guidance section text for `/steer`. This is
the full non-I/O half of "sensor state -> actuator decision" without
reconstructing the orchestrator's I/O side (label swaps, re-enqueue calls,
HITL escalation), which remains exclusively
``test_orchestrator_human_steering.py``'s job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from human_steering import apply_steering, fenced_steering_guidance
from issue_store import IssueStoreStage
from models import SteeringState

pytestmark = pytest.mark.scenario_loops

_ISSUE_NUMBER = 501
_AUTHORIZED_LOGIN = "authorized-operator"
_UNAUTHORIZED_LOGIN = "random-passerby"

_KNOWN_PHASES = {stage.value for stage in IssueStoreStage} - {
    IssueStoreStage.MERGED.value
}


class _RealStateSteeringStore:
    """Minimal real (non-mock) ``human_steering`` state store.

    Mirrors the ``StateData.human_steering: dict[str, SteeringState]``
    contract (str(issue_id)-keyed per steering-global-constraints) without
    pulling in the full persistence stack — the loop only calls
    ``get_human_steering`` / ``set_human_steering``.
    """

    def __init__(self) -> None:
        self._by_issue: dict[str, SteeringState] = {}

    def get_human_steering(self, issue_key: str) -> SteeringState:
        return self._by_issue.get(issue_key, SteeringState())

    def set_human_steering(self, issue_key: str, value: SteeringState) -> None:
        self._by_issue[issue_key] = value


def _build_loop(
    tmp_path: Path,
    *,
    github: object,
    state: object,
    max_redos: int = 3,
    authorized_users: list[str] | None = None,
) -> object:
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415
    from tests.scenarios.catalog import LoopCatalog  # noqa: PLC0415
    from tests.scenarios.catalog import (  # noqa: PLC0415  # registration side-effect
        loop_registrations as _loop_registrations,
    )

    _ = _loop_registrations

    bg = make_bg_loop_deps(tmp_path)
    # human_steering_* fields aren't in ConfigFactory.create's whitelist
    # (Task 5 feature, not yet threaded through); set directly on the
    # constructed HydraFlowConfig, same pattern as
    # tests/test_orchestrator_human_steering.py.
    bg.config.human_steering_enabled = True
    bg.config.human_steering_max_redos = max_redos
    # Allowlist (Task 1): only these logins' directives are honored. Empty
    # allowlist -> honor nobody (safe default-on) is what the "unauthorized
    # directive is ignored" scenario below exercises by omission.
    bg.config.human_steering_authorized_users = (
        authorized_users if authorized_users is not None else [_AUTHORIZED_LOGIN]
    )
    from base_background_loop import LoopDeps  # noqa: PLC0415

    loop_deps = LoopDeps(
        event_bus=bg.bus,
        stop_event=bg.stop_event,
        status_cb=bg.status_cb,
        enabled_cb=bg.enabled_cb,
        sleep_fn=bg.sleep_fn,
    )
    return LoopCatalog.instantiate(
        "human_steering",
        ports={
            "github": github,
            "human_steering_state": state,
            "human_steering_active_issues_cb": lambda: [_ISSUE_NUMBER],
        },
        config=bg.config,
        deps=loop_deps,
    )


class TestHumanSteeringScenario:
    """Task 8/12 — sensor path + actuator-decision seam, allowlist enforced."""

    async def test_directive_sequence_updates_state_with_redo_high_water_mark(
        self, tmp_path: Path
    ) -> None:
        """Seeded /pause, /steer, /resume, /redo in increasing created_at order:
        flow ends running (resume undoes pause), guidance sticks, redo_phase
        fires on tick 1, survives tick 2 unconsumed, and once the actuator
        clears it does not resurrect from the same stale comment on tick 3
        (created_at high-water-mark)."""
        from tests.scenarios.fakes.mock_world import MockWorld  # noqa: PLC0415

        world = MockWorld(tmp_path)
        world.github.add_issue(
            _ISSUE_NUMBER, title="steer me", body="...", labels=["in-progress"]
        )
        world.github.add_seeded_comment(
            _ISSUE_NUMBER,
            "/pause",
            login=_AUTHORIZED_LOGIN,
            created_at="2026-07-01T00:00:00Z",
        )
        world.github.add_seeded_comment(
            _ISSUE_NUMBER,
            "/steer focus on tests",
            login=_AUTHORIZED_LOGIN,
            created_at="2026-07-01T00:01:00Z",
        )
        world.github.add_seeded_comment(
            _ISSUE_NUMBER,
            "/resume",
            login=_AUTHORIZED_LOGIN,
            created_at="2026-07-01T00:02:00Z",
        )
        world.github.add_seeded_comment(
            _ISSUE_NUMBER,
            "/redo plan",
            login=_AUTHORIZED_LOGIN,
            created_at="2026-07-01T00:03:00Z",
        )

        state = _RealStateSteeringStore()
        loop = _build_loop(tmp_path, github=world.github, state=state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["updated"] == 1

        written = state.get_human_steering(str(_ISSUE_NUMBER))
        # /pause then /resume -> flow settles back to running (declarative,
        # latest-wins within the tick).
        assert written.flow == "running"
        assert written.guidance == "focus on tests"
        # /redo plan is imperative and past the (initially None) high-water
        # mark -> fires on this first tick.
        assert written.redo_phase == "plan"
        assert written.last_applied_ts == "2026-07-01T00:03:00Z"

        # Actuator-decision seam: feed the loop's real persisted state into
        # the same pure function HydraFlowOrchestrator._apply_human_steering
        # enacts verbatim. redo_phase="plan" is a known phase and under cap
        # -> the decision re-enqueues to it.
        decision = apply_steering(written, str(_ISSUE_NUMBER), _KNOWN_PHASES, 3)
        assert decision.skip is False
        assert decision.park is False
        assert decision.redo_phase == "plan"
        # /steer guidance reaches the ADR-0092 single fence choke point.
        fenced = fenced_steering_guidance(decision.guidance)
        assert "## Human Steering Guidance" in fenced
        assert "focus on tests" in fenced

        # Second tick with the *same* comments seeded (nothing new posted):
        # the sensor preserves an unconsumed redo_phase across ticks (the
        # actuator hasn't cleared it yet, see human_steering_loop.py's
        # `d.redo_phase or prev.redo_phase`) rather than dropping it, so it
        # is still "plan" here — the same behavior
        # test_human_steering_loop.py::test_loop_preserves_unconsumed_redo_on_retick
        # proves at the unit level.
        result2 = await loop._do_work()
        assert result2["status"] == "ok"

        written2 = state.get_human_steering(str(_ISSUE_NUMBER))
        assert written2.redo_phase == "plan"
        assert written2.flow == "running"
        assert written2.guidance == "focus on tests"
        assert written2.last_applied_ts == "2026-07-01T00:03:00Z"

        # Now simulate the actuator consuming the redo (as
        # HydraFlowOrchestrator._apply_human_steering does: it re-enqueues
        # the phase and persists redo_phase=None). A third tick over the
        # *same* stale /redo comment must NOT resurrect it: the comment's
        # created_at ("...:03:00Z") is no longer past last_applied_ts
        # ("...:03:00Z", equal), so parse_directives' `ts > last_applied_ts`
        # gate is false — this is the actual high-water-mark proof.
        state.set_human_steering(
            str(_ISSUE_NUMBER),
            SteeringState(
                guidance=written2.guidance,
                flow=written2.flow,
                redo_phase=None,
                redo_count=1,
                last_applied_ts=written2.last_applied_ts,
            ),
        )
        result3 = await loop._do_work()
        assert result3["status"] == "ok"

        written3 = state.get_human_steering(str(_ISSUE_NUMBER))
        assert written3.redo_phase is None, (
            "a stale /redo comment at or before the high-water-mark must "
            "not re-fire once the actuator has consumed it"
        )
        assert written3.flow == "running"
        assert written3.guidance == "focus on tests"

    async def test_pause_without_resume_persists_paused_flow_and_actuator_skips(
        self, tmp_path: Path
    ) -> None:
        """Isolates the running->paused transition (no /resume in history)
        and proves the actuator decision derived from it is skip=True — the
        brief's "/pause -> the issue is skipped by the actuator" assertion,
        driven from the loop's real sensed output rather than a hand-built
        SteeringState fixture."""
        from tests.scenarios.fakes.mock_world import MockWorld  # noqa: PLC0415

        world = MockWorld(tmp_path)
        world.github.add_issue(
            _ISSUE_NUMBER, title="steer me", body="...", labels=["in-progress"]
        )
        world.github.add_seeded_comment(
            _ISSUE_NUMBER,
            "/pause",
            login=_AUTHORIZED_LOGIN,
            created_at="2026-07-01T00:00:00Z",
        )

        state = _RealStateSteeringStore()
        loop = _build_loop(tmp_path, github=world.github, state=state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        written = state.get_human_steering(str(_ISSUE_NUMBER))
        assert written.flow == "paused"
        assert written.guidance is None
        assert written.redo_phase is None

        decision = apply_steering(written, str(_ISSUE_NUMBER), _KNOWN_PHASES, 3)
        assert decision.skip is True, "a paused issue's decision must skip scheduling"
        assert decision.park is False
        assert decision.redo_phase is None

    async def test_unauthorized_directive_is_sensed_and_ignored(
        self, tmp_path: Path
    ) -> None:
        """An UNAUTHORIZED login's /pause is fetched by the sensor (the
        comment exists on the issue) but dropped by the Task 1 allowlist
        choke point in `parse_directives` before any verb is honored — the
        persisted state is untouched (still the SteeringState default), and
        the actuator decision derived from it is a no-op (skip=False,
        park=False, redo_phase=None): exactly as if the comment had never
        been posted."""
        from tests.scenarios.fakes.mock_world import MockWorld  # noqa: PLC0415

        world = MockWorld(tmp_path)
        world.github.add_issue(
            _ISSUE_NUMBER, title="steer me", body="...", labels=["in-progress"]
        )
        world.github.add_seeded_comment(
            _ISSUE_NUMBER,
            "/pause",
            login=_UNAUTHORIZED_LOGIN,
            created_at="2026-07-01T00:00:00Z",
        )

        state = _RealStateSteeringStore()
        # Allowlist only contains _AUTHORIZED_LOGIN; _UNAUTHORIZED_LOGIN's
        # comment must be filtered out entirely.
        loop = _build_loop(
            tmp_path,
            github=world.github,
            state=state,
            authorized_users=[_AUTHORIZED_LOGIN],
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["updated"] == 1  # the issue was still processed...

        written = state.get_human_steering(str(_ISSUE_NUMBER))
        # ...but its state is untouched: the unauthorized /pause never
        # reached parse_directives' verb handling, so flow stays at the
        # SteeringState default ("running"), not "paused".
        assert written.flow == "running"
        assert written.guidance is None
        assert written.redo_phase is None
        assert written.last_applied_ts is None

        decision = apply_steering(written, str(_ISSUE_NUMBER), _KNOWN_PHASES, 3)
        assert decision.skip is False
        assert decision.park is False
        assert decision.redo_phase is None

    async def test_empty_allowlist_honors_nobody(self, tmp_path: Path) -> None:
        """Task 1's safe-default-on: an empty
        ``human_steering_authorized_users`` allowlist drops every directive,
        including one from a login that would otherwise be a plausible
        operator — "empty allowlist" is not "allow all", it's "allow none"."""
        from tests.scenarios.fakes.mock_world import MockWorld  # noqa: PLC0415

        world = MockWorld(tmp_path)
        world.github.add_issue(
            _ISSUE_NUMBER, title="steer me", body="...", labels=["in-progress"]
        )
        world.github.add_seeded_comment(
            _ISSUE_NUMBER,
            "/abort",
            login=_AUTHORIZED_LOGIN,
            created_at="2026-07-01T00:00:00Z",
        )

        state = _RealStateSteeringStore()
        loop = _build_loop(
            tmp_path, github=world.github, state=state, authorized_users=[]
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        written = state.get_human_steering(str(_ISSUE_NUMBER))
        assert written.flow == "running"

        decision = apply_steering(written, str(_ISSUE_NUMBER), _KNOWN_PHASES, 3)
        assert decision.park is False
