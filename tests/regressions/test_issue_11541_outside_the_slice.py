"""Outside the Plan canary's bound, nothing moved (#11541).

The canary's defining property, written as a **differential** proof rather than
a descriptive one: the same director, over the same boundary, with the actuator
fully wired and the bound not covering it, must record byte-identical evidence
to the same director with no actuator at all — and must spawn nothing.

Four ways out of the bound are covered, because each is a different clause of
``plan_broker.plan_canary_covers`` and a regression could reopen any one of
them independently:

* the dial is empty (an untouched deployment);
* the dial names another repository;
* the dial names this repository but the boundary is not ``PLAN`` — which is
  the whole of "implement, review and HITL remain Classic";
* the dial was cleared while the process was running (the one-action rollback,
  taking effect on the next boundary rather than the next restart).

Three non-vacuity tests sit beside them: the same director *inside* the bound
does dispatch, does record a receipt, and records evidence the uncovered arms
can be told apart from. Without those, deleting the feature would pass every
assertion above.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from director_broker import ShadowDispatchBroker
from director_sandbox import ProbeEvidence
from director_shadow_log import ShadowObservationLog
from director_turn_runner import CAPSULE_CLOSE, CAPSULE_OPEN, DirectorTurnResult
from driver_contracts import DriverPhase
from execution import SimpleResult
from fable_director import FableDirector
from issue_driver import AdvanceOutcome, DriverAdvance, IssueDriver
from models import Task
from plan_broker import PlanCanaryLatch, plan_canary_covers
from plan_worker_runner import PlanWorkerRunner
from scheduling_model import ExecutionRuntime, SchedulingModel

if TYPE_CHECKING:
    from pathlib import Path

CANARY_REPO = "acme/widgets"
PLAN_LABEL = "hydraflow-plan"
ROUTE_REVISION = "route-v1"
STAGE_LABELS = {
    "PLAN": PLAN_LABEL,
    "READY": "hydraflow-ready",
    "REVIEW": "hydraflow-review",
    "HITL_WAIT": "hydraflow-hitl",
}
EVIDENCE = ProbeEvidence(
    agent_cli_version="2.1.239",
    residual_agents=5,
    residual_skills=15,
    residual_slash_commands=42,
)
CLEAN_INIT = {
    "type": "system",
    "subtype": "init",
    "tools": [],
    "mcp_servers": [],
    "plugins": [],
    "agents": [],
    "skills": [],
    "slash_commands": [],
    "version": "2.1.239",
}

#: Fields whose value is a clock reading or a random id. Normalised out of the
#: comparison because they differ between any two runs, canary or not — and
#: pinned by name so the comparison cannot be quietly widened into vacuity.
VOLATILE_FIELDS = ("recorded_at",)


class ScriptedTurn:
    """One director turn asking for one catalogued worker. Spawns nothing.

    The role is a parameter because the canary's phase clause can only be
    *killed* by a request the rest of the machinery would otherwise allow: at
    IMPLEMENT a ``planner`` is refused by the capsule's role allow-list anyway,
    so a planner-only script can never tell "the bound excluded this phase"
    from "the catalog excluded this role".
    """

    def __init__(self, role: str = "planner", family: str = "claude-sonnet") -> None:
        self.cli_version = "2.1.239"
        self.turns = 0
        self._role = role
        self._family = family

    async def preflight(self) -> str:
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        """Answer *from the capsule*, the way a real director has to.

        The fencing tokens are read back out of the capsule rather than
        hardcoded. A hardcoded driver id makes every request for a second issue
        fail ``DRIVER_IDENTITY_MISMATCH``, which silently turns a latch test
        into a fence test that would pass with the latch deleted — which is
        exactly what happened on the first draft of this file.
        """
        self.turns += 1
        payload = prompt.split(CAPSULE_OPEN, 1)[1].split(CAPSULE_CLOSE, 1)[0]
        lease = json.loads(payload)["lease"]
        command = {
            "kind": "dispatch_workers",
            "rationale": "the plan needs the module map first",
            "dispatches": [
                {
                    "request_id": "req-1",
                    "driver_id": lease["driver_id"],
                    "epoch": lease["epoch"],
                    "phase_attempt": lease["phase_attempt"],
                    "worker_role": self._role,
                    "model_requirement": {
                        "kind": "literal_family",
                        "value": self._family,
                    },
                    "task_contract": "draft the plan",
                    "reason": "the plan needs drafting",
                    "expected_route_policy_revision": ROUTE_REVISION,
                    "idempotency_key": f"key-{lease['issue_number']}",
                }
            ],
        }
        return DirectorTurnResult(
            frames=[
                CLEAN_INIT,
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": json.dumps(command)}]
                    },
                },
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "total_cost_usd": 0.0,
                },
            ],
            exit_code=0,
        )


class NeverSpawns:
    """A SubprocessRunner the injected spawn double should never reach."""

    async def run_simple(self, *args, **kwargs):
        raise AssertionError("the real spawn seam ran in a regression test")


class SpawnCounter:
    """Stands in for ``run_lightweight_agent`` and records every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls.append(kwargs)
        spawn_out = kwargs.get("spawn_out")
        if spawn_out is not None:
            spawn_out.update(
                {
                    # The seam sets this on the last line before it starts the
                    # process. A double that filled `model` without it models a
                    # CAUGHT MINT FAILURE — which is a real thing the seam does
                    # and a different one, and omitting it here silently turned
                    # this file's dispatch non-vacuity into a refusal test.
                    "spawned": True,
                    "model": kwargs["model"],
                    "provider": "gateway",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                    "route_decision_id": "dec_x",
                }
            )
        return SimpleResult(stdout="## Modules\n\nthe map", returncode=0)


def _config(tmp_path: Path, canary: str) -> Any:
    from config import HydraFlowConfig

    return HydraFlowConfig(
        state_file=tmp_path / "state.json",
        repo=CANARY_REPO,
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        fable_plan_canary_repo=canary,
    )


def _driver() -> IssueDriver:
    return IssueDriver(
        issue_number=7,
        driver_id="drv-7",
        repo_slug=CANARY_REPO,
        adapters={},
        labels=object(),  # type: ignore[arg-type]
        journal=object(),  # type: ignore[arg-type]
        stage_labels=STAGE_LABELS,
        driver_state="PLAN",
    )


def _advance(phase: DriverPhase = DriverPhase.PLAN) -> DriverAdvance:
    return DriverAdvance(
        issue_number=7,
        driver_id="drv-7",
        epoch=0,
        phase=phase,
        outcome=AdvanceOutcome.COMMITTED,
        state="PLAN",
    )


def _build(
    tmp_path: Path,
    *,
    name: str,
    canary: str | None,
    wired: bool,
    turn: ScriptedTurn | None = None,
):
    """One director, with the actuator wired or entirely absent."""
    log = ShadowObservationLog(tmp_path / f"{name}-shadow.jsonl")
    spawn = SpawnCounter()
    dispatcher = None
    is_covered = None
    if wired:
        config = _config(tmp_path, canary or "")
        dispatcher = PlanWorkerRunner(
            config=config,
            route_policy_revision=ROUTE_REVISION,
            runner=NeverSpawns(),  # type: ignore[arg-type]
            spawn=spawn,
        )
        is_covered = lambda phase: plan_canary_covers(config, phase=phase)  # noqa: E731
    director = FableDirector(
        runner=turn or ScriptedTurn(),  # type: ignore[arg-type]
        broker=ShadowDispatchBroker(),
        shadow_log=log,
        evidence=EVIDENCE,
        repo_slug=CANARY_REPO,
        route_policy_revision=ROUTE_REVISION,
        stage_labels=STAGE_LABELS,
        usd_budget_per_boundary=5.0,
        dispatcher=dispatcher,
        is_covered=is_covered,
        latch=PlanCanaryLatch(ttl_seconds=900) if wired else None,
    )
    return director, log, spawn


async def _observe(director: FableDirector, phase: DriverPhase = DriverPhase.PLAN):
    await director.observe_boundary(
        task=Task(id=7, title="make the widget faster", tags=[PLAN_LABEL]),
        advance=_advance(phase),
        driver=_driver(),
    )


def _evidence(log: ShadowObservationLog) -> list[dict[str, object]]:
    rows = []
    for observation in log.recent():
        row = observation.model_dump(mode="json")
        for field in VOLATILE_FIELDS:
            row.pop(field, None)
        rows.append(row)
    return rows


async def _run(
    tmp_path: Path,
    *,
    name: str,
    canary: str | None,
    wired: bool,
    phase,
    turn: ScriptedTurn | None = None,
):
    director, log, spawn = _build(
        tmp_path, name=name, canary=canary, wired=wired, turn=turn
    )
    await _observe(director, phase)
    return _evidence(log), spawn.calls


@pytest.fixture
async def baseline(tmp_path: Path):
    """The shadow arm: no dispatcher, no latch, no coverage predicate."""
    return await _run(
        tmp_path, name="baseline", canary=None, wired=False, phase=DriverPhase.PLAN
    )


class TestOutsideTheBoundNothingMoves:
    async def test_an_untouched_deployment_records_the_shadow_evidence(
        self, tmp_path: Path, baseline
    ) -> None:
        rows, _ = baseline

        armed, _calls = await _run(
            tmp_path, name="empty", canary="", wired=True, phase=DriverPhase.PLAN
        )

        assert armed == rows

    async def test_an_untouched_deployment_spawns_nothing(self, tmp_path: Path) -> None:
        _rows, calls = await _run(
            tmp_path, name="empty", canary="", wired=True, phase=DriverPhase.PLAN
        )

        assert calls == []

    async def test_a_canary_armed_for_another_repository_records_the_same(
        self, tmp_path: Path, baseline
    ) -> None:
        rows, _ = baseline

        other, _calls = await _run(
            tmp_path,
            name="other",
            canary="acme/other",
            wired=True,
            phase=DriverPhase.PLAN,
        )

        assert other == rows

    async def test_a_canary_armed_for_another_repository_spawns_nothing(
        self, tmp_path: Path
    ) -> None:
        _rows, calls = await _run(
            tmp_path,
            name="other",
            canary="acme/other",
            wired=True,
            phase=DriverPhase.PLAN,
        )

        assert calls == []

    @pytest.mark.parametrize(
        "phase",
        [
            pytest.param(DriverPhase.IMPLEMENT, id="implement"),
            pytest.param(DriverPhase.REVIEW, id="review"),
            pytest.param(DriverPhase.HITL, id="hitl"),
        ],
    )
    async def test_a_later_stage_in_the_canary_repository_spawns_nothing(
        self, tmp_path: Path, phase: DriverPhase
    ) -> None:
        # "Implement, review, and HITL remain Classic", at the seam that would
        # have to break for them not to.
        _rows, calls = await _run(
            tmp_path,
            name=f"stage-{phase.value}",
            canary=CANARY_REPO,
            wired=True,
            phase=phase,
        )

        assert calls == []

    @pytest.mark.parametrize(
        ("phase", "role", "family"),
        [
            pytest.param(
                DriverPhase.IMPLEMENT, "explorer", "claude-sonnet", id="implement"
            ),
            pytest.param(DriverPhase.REVIEW, "architect", "claude-opus", id="review"),
        ],
    )
    async def test_a_later_stage_is_not_even_offered_to_the_canary(
        self, tmp_path: Path, phase: DriverPhase, role: str, family: str
    ) -> None:
        """The phase clause itself, isolated from the defences behind it.

        Mutation testing caught two earlier versions of this passing with
        ``plan_canary_covers``'s phase clause **deleted** — first because the
        tier resolver also refuses a non-PLAN phase, then because a `planner`
        is refused at IMPLEMENT by the capsule's role allow-list anyway. Both
        defences are right and both assertions were blind.

        So the role here is one the catalog *does* allow at the phase under
        test: an explorer at IMPLEMENT, an architect at REVIEW. With the clause
        present the boundary is never offered to the canary and records no
        receipt at all; without it the request is admitted and dispatched.

        HITL is absent on purpose. ``WORKER_CATALOG`` catalogues no role for it,
        so there is no request that could distinguish the clause from the
        catalog — the bound and the catalog agree there, and a test that cannot
        fail is worse than none.
        """
        rows, calls = await _run(
            tmp_path,
            name=f"offered-{phase.value}",
            canary=CANARY_REPO,
            wired=True,
            phase=phase,
            turn=ScriptedTurn(role=role, family=family),
        )

        assert calls == []
        assert [row["dispatched"] for row in rows] == [[]]

    async def test_clearing_the_dial_mid_run_stops_the_next_boundary(
        self, tmp_path: Path
    ) -> None:
        # The one-action rollback at the seam it has to act on: the dispatcher
        # object still exists, and what stops it is the live predicate.
        from config import HydraFlowConfig

        config = HydraFlowConfig(
            state_file=tmp_path / "state.json",
            repo=CANARY_REPO,
            scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
            execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
            fable_plan_canary_repo=CANARY_REPO,
        )
        spawn = SpawnCounter()
        director = FableDirector(
            runner=ScriptedTurn(),  # type: ignore[arg-type]
            broker=ShadowDispatchBroker(),
            shadow_log=ShadowObservationLog(tmp_path / "rollback-shadow.jsonl"),
            evidence=EVIDENCE,
            repo_slug=CANARY_REPO,
            route_policy_revision=ROUTE_REVISION,
            stage_labels=STAGE_LABELS,
            usd_budget_per_boundary=5.0,
            dispatcher=PlanWorkerRunner(
                config=config,
                route_policy_revision=ROUTE_REVISION,
                runner=NeverSpawns(),  # type: ignore[arg-type]
                spawn=spawn,
            ),
            is_covered=lambda phase: plan_canary_covers(config, phase=phase),
            latch=PlanCanaryLatch(ttl_seconds=900),
        )
        await _observe(director)
        spawned_while_armed = len(spawn.calls)

        object.__setattr__(config, "fable_plan_canary_repo", "")
        await _observe(director)

        assert (spawned_while_armed, len(spawn.calls)) == (1, 1)


class TestInsideTheBoundSomethingActuallyHappens:
    """Without these, deleting the feature would pass every test above."""

    async def test_the_canary_repository_at_plan_spawns_one_child(
        self, tmp_path: Path
    ) -> None:
        _rows, calls = await _run(
            tmp_path,
            name="armed",
            canary=CANARY_REPO,
            wired=True,
            phase=DriverPhase.PLAN,
        )

        assert len(calls) == 1

    async def test_the_boundary_records_a_receipt(self, tmp_path: Path) -> None:
        # Asserted on the STATUS, not just the count: this is the file's
        # dispatch non-vacuity, and a refusal receipt satisfies a bare count
        # just as well as an accepted one — which is exactly what happened when
        # this file's spawn double was left without ``spawned``.
        rows, _calls = await _run(
            tmp_path,
            name="armed",
            canary=CANARY_REPO,
            wired=True,
            phase=DriverPhase.PLAN,
        )

        assert [r["status"] for r in rows[0]["dispatched"]] == ["accepted"]
        assert [node["dispatched"] for node in rows[0]["would_dispatch"]] == [True]

    async def test_the_armed_evidence_differs_from_the_shadow_evidence(
        self, tmp_path: Path, baseline
    ) -> None:
        # The comparison in the class above is only meaningful if these two are
        # actually distinguishable by it.
        rows, _ = baseline

        armed, _calls = await _run(
            tmp_path,
            name="armed",
            canary=CANARY_REPO,
            wired=True,
            phase=DriverPhase.PLAN,
        )

        assert armed != rows


class TestOnlyOneIssueAtATimeIsFableDirected:
    """The issue's first acceptance criterion, at the seam that enforces it.

    ``tests/test_plan_broker.py`` proves the latch in isolation. This proves the
    director actually consults it, which no unit test of the latch can: a
    director that built one and never called ``claim`` would pass every test
    there.
    """

    async def _director(self, tmp_path: Path, spawn: SpawnCounter):
        config = _config(tmp_path, CANARY_REPO)
        return FableDirector(
            runner=ScriptedTurn(),  # type: ignore[arg-type]
            broker=ShadowDispatchBroker(),
            shadow_log=ShadowObservationLog(tmp_path / "latch-shadow.jsonl"),
            evidence=EVIDENCE,
            repo_slug=CANARY_REPO,
            route_policy_revision=ROUTE_REVISION,
            stage_labels=STAGE_LABELS,
            usd_budget_per_boundary=5.0,
            dispatcher=PlanWorkerRunner(
                config=config,
                route_policy_revision=ROUTE_REVISION,
                runner=NeverSpawns(),  # type: ignore[arg-type]
                spawn=spawn,
            ),
            is_covered=lambda phase: plan_canary_covers(config, phase=phase),
            latch=PlanCanaryLatch(ttl_seconds=900),
        )

    async def _observe_issue(self, director, issue: int) -> None:
        await director.observe_boundary(
            task=Task(id=issue, title="driven issue", tags=[PLAN_LABEL]),
            advance=DriverAdvance(
                issue_number=issue,
                driver_id=f"drv-{issue}",
                epoch=0,
                phase=DriverPhase.PLAN,
                outcome=AdvanceOutcome.COMMITTED,
                state="PLAN",
            ),
            driver=IssueDriver(
                issue_number=issue,
                driver_id=f"drv-{issue}",
                repo_slug=CANARY_REPO,
                adapters={},
                labels=object(),  # type: ignore[arg-type]
                journal=object(),  # type: ignore[arg-type]
                stage_labels=STAGE_LABELS,
                driver_state="PLAN",
            ),
        )

    async def test_a_second_issue_dispatches_nothing_while_the_first_holds_the_slot(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnCounter()
        director = await self._director(tmp_path, spawn)

        await self._observe_issue(director, 7)
        after_first = len(spawn.calls)
        await self._observe_issue(director, 9)

        assert (after_first, len(spawn.calls)) == (1, 1)

    async def test_the_refused_issue_gets_a_receipt_naming_the_slot(
        self, tmp_path: Path
    ) -> None:
        from director_shadow_log import ShadowObservationLog as _Log  # noqa: F401

        spawn = SpawnCounter()
        director = await self._director(tmp_path, spawn)

        await self._observe_issue(director, 7)
        await self._observe_issue(director, 9)

        refused = director.shadow_log.recent()[-1].dispatched
        assert [row["reason"] for row in refused] == ["canary_slot_held"]

    async def test_the_slot_is_freed_when_its_issue_leaves_plan(
        self, tmp_path: Path
    ) -> None:
        # Otherwise the canary would run exactly one issue per TTL window.
        spawn = SpawnCounter()
        director = await self._director(tmp_path, spawn)
        await self._observe_issue(director, 7)

        await director.observe_boundary(
            task=Task(id=7, title="driven issue", tags=[PLAN_LABEL]),
            advance=DriverAdvance(
                issue_number=7,
                driver_id="drv-7",
                epoch=0,
                phase=DriverPhase.IMPLEMENT,
                outcome=AdvanceOutcome.COMMITTED,
                state="READY",
            ),
            driver=IssueDriver(
                issue_number=7,
                driver_id="drv-7",
                repo_slug=CANARY_REPO,
                adapters={},
                labels=object(),  # type: ignore[arg-type]
                journal=object(),  # type: ignore[arg-type]
                stage_labels=STAGE_LABELS,
                driver_state="READY",
            ),
        )
        await self._observe_issue(director, 9)

        assert len(spawn.calls) == 2
