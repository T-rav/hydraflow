"""MockWorld scenario for `HumanSteeringLoop` (ADR-0099 #4, Task 8).

Task 5's registration-only builder (``_build_human_steering`` in
``tests/scenarios/catalog/loop_registrations.py``) proves the loop wires into
the catalog and instantiates cleanly with clean-slate defaults. This scenario
exercises the sensing path end-to-end: a seeded sequence of GitHub-comment
directives ticked through the real ``HumanSteeringLoop._do_work`` and a real
(non-mock) per-issue ``SteeringState`` store, proving the persisted state
after each tick matches ``human_steering.parse_directives`` semantics wired
through the loop rather than asserted against the pure function directly.

Harness note / deviation from the brief: the brief asks to seed comments via
FakeGitHub directly. ``FakeGitHub.list_issue_comments`` (src/mockworld/fakes/
fake_github.py) wraps every seeded comment body with the *same* hardcoded
``created_at`` ("2026-01-01T00:00:00Z") — by design it only round-trips
``FakeIssue.comments: list[str]``, with no per-comment timestamp field. That
collapses the high-water-mark this scenario needs to prove (imperative
``/redo`` firing once, not re-firing on a later tick) into a same-timestamp
tie, which `parse_directives` treats as *not* past the mark (`ts > last_ts`
is false when equal). Rather than invent a harness call that does not exist,
this scenario still builds the loop the same way the catalog does (through
``LoopCatalog.instantiate("human_steering", ...)``, proving the Task 5 wiring)
and still seeds the issue itself in the real ``FakeGitHub`` (so labels/issue
existence are real MockWorld state), but supplies comment fetch via a thin
wrapper that delegates to the real ``FakeGitHub`` for everything except
returning the seeded comments with distinct, real ``created_at`` values —
the one piece of the port contract the fake cannot currently vary. This
satisfies "follow the harness API exactly for what it can drive" while
keeping the timestamp control the scenario is actually about.

The actuator half (``human_steering.apply_steering`` enacted by
``HydraFlowOrchestrator._apply_human_steering`` — pause->skip, redo->
re-enqueue, guidance->fenced prompt) is not reachable through the scenario
catalog: the catalog only wires loops (``LoopCatalog.instantiate`` returns a
``BaseBackgroundLoop``), and the actuator lives on ``HydraFlowOrchestrator``
itself, constructed and covered directly in
``tests/test_orchestrator_human_steering.py``. This scenario is
sensor-only by construction; it does not duplicate that orchestrator-level
coverage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from models import SteeringState

pytestmark = pytest.mark.scenario_loops

_ISSUE_NUMBER = 501


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


class _TimestampedCommentsGitHub:
    """Wraps a real ``FakeGitHub`` to supply distinct comment ``created_at``.

    Delegates every port method to the wrapped ``FakeGitHub`` except
    ``list_issue_comments``, which the real fake hardcodes to a single
    timestamp for all comments (see module docstring). Comments are seeded
    here as full port-contract dicts (``user.login`` / ``body`` /
    ``created_at``) in increasing ``created_at`` order, exactly the shape
    ``HumanSteeringLoop`` -> ``parse_directives`` consumes.
    """

    def __init__(self, real_github: Any, issue_number: int) -> None:
        self._real = real_github
        self._issue_number = issue_number
        self._comments: list[dict[str, Any]] = []

    def seed_comment(self, body: str, created_at: str) -> None:
        self._comments.append(
            {"user": {"login": "fake-human"}, "body": body, "created_at": created_at}
        )

    async def list_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        if issue_number != self._issue_number:
            return await self._real.list_issue_comments(issue_number)
        return list(self._comments)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _build_loop(tmp_path: Path, *, github: Any, state: Any, max_redos: int = 3) -> Any:
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
    # Comments in this scenario are seeded as authored by "fake-human"
    # (see _TimestampedCommentsGitHub.seed_comment); the loop now filters
    # directives through an authorization allowlist (Task 1), so it must
    # include that login or every directive is silently dropped.
    bg.config.human_steering_authorized_users = ["fake-human"]
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
    """Task 8 — sensor path: comments -> HumanSteeringLoop -> persisted state."""

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

        github = _TimestampedCommentsGitHub(world.github, _ISSUE_NUMBER)
        github.seed_comment("/pause", "2026-07-01T00:00:00Z")
        github.seed_comment("/steer focus on tests", "2026-07-01T00:01:00Z")
        github.seed_comment("/resume", "2026-07-01T00:02:00Z")
        github.seed_comment("/redo shape", "2026-07-01T00:03:00Z")

        state = _RealStateSteeringStore()
        loop = _build_loop(tmp_path, github=github, state=state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["updated"] == 1

        written = state.get_human_steering(str(_ISSUE_NUMBER))
        # /pause then /resume -> flow settles back to running (declarative,
        # latest-wins within the tick).
        assert written.flow == "running"
        assert written.guidance == "focus on tests"
        # /redo shape is imperative and past the (initially None) high-water
        # mark -> fires on this first tick.
        assert written.redo_phase == "shape"
        assert written.last_applied_ts == "2026-07-01T00:03:00Z"

        # Second tick with the *same* comments seeded (nothing new posted):
        # the sensor preserves an unconsumed redo_phase across ticks (the
        # actuator hasn't cleared it yet, see human_steering_loop.py's
        # `d.redo_phase or prev.redo_phase`) rather than dropping it, so it
        # is still "shape" here — the same behavior
        # test_human_steering_loop.py::test_loop_preserves_unconsumed_redo_on_retick
        # proves at the unit level.
        result2 = await loop._do_work()
        assert result2["status"] == "ok"

        written2 = state.get_human_steering(str(_ISSUE_NUMBER))
        assert written2.redo_phase == "shape"
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

    async def test_pause_without_resume_persists_paused_flow(
        self, tmp_path: Path
    ) -> None:
        """Isolates the running->paused transition (no /resume in history)."""
        from tests.scenarios.fakes.mock_world import MockWorld  # noqa: PLC0415

        world = MockWorld(tmp_path)
        world.github.add_issue(
            _ISSUE_NUMBER, title="steer me", body="...", labels=["in-progress"]
        )

        github = _TimestampedCommentsGitHub(world.github, _ISSUE_NUMBER)
        github.seed_comment("/pause", "2026-07-01T00:00:00Z")

        state = _RealStateSteeringStore()
        loop = _build_loop(tmp_path, github=github, state=state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        written = state.get_human_steering(str(_ISSUE_NUMBER))
        assert written.flow == "paused"
        assert written.guidance is None
        assert written.redo_phase is None
