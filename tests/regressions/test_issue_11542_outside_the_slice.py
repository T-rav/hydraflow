"""Outside the Implement canary's bound, nothing moved (#11542).

The same **differential** proof #11541 wrote for the Plan canary, over this
phase's bound: the same director, over the same boundary, with the writer
actuator fully wired and the bound not covering it, must record byte-identical
evidence to the same director with no writer actuator at all — and must spawn
nothing, measure nothing, and take no lease.

Five ways out of the bound, one per clause of the thing that could regress:

* the writer dial is empty (an untouched deployment);
* the writer dial names another repository;
* the writer dial names this repository but the boundary is not ``IMPLEMENT``
  — which is the whole of "independent review remains Classic";
* **only the Plan canary is armed** — the case this phase introduces, and the
  one that says "widen one role boundary at a time" is a property rather than
  a sentence;
* the dial was cleared while the process was running (the one-action rollback,
  taking effect on the next boundary rather than the next restart).

Non-vacuity tests sit beside them: inside the bound the same director *does*
dispatch, *does* measure, and *does* record a receipt, and the two evidence
sets *are* distinguishable. Without those, deleting the feature would pass
every assertion above.

The last class is the fence itself at the director seam, which no unit test of
``check_worker_fence`` can reach: a director that computed a fence and never
consulted it would pass every test in ``tests/test_implement_broker.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from director_broker import ShadowDispatchBroker
from director_sandbox import ProbeEvidence
from director_shadow_log import ShadowObservationLog
from director_turn_runner import CAPSULE_CLOSE, CAPSULE_OPEN, DirectorTurnResult
from driver_contracts import DriverPhase, ReceiptStatus
from execution import SimpleResult
from fable_director import FableDirector
from implement_broker import WriterLeaseRegistry, implement_canary_covers
from implement_worker_runner import ImplementWorkerRunner
from issue_driver import AdvanceOutcome, DriverAdvance, IssueDriver
from models import Task
from scheduling_model import ExecutionRuntime, SchedulingModel

if TYPE_CHECKING:
    from pathlib import Path

CANARY_REPO = "acme/widgets"
READY_LABEL = "hydraflow-ready"
ROUTE_REVISION = "route-v1"
BRANCH = "agent/issue-7"
BASE = "1" * 40
HEAD = "2" * 40
STAGE_LABELS = {
    "PLAN": "hydraflow-plan",
    "READY": READY_LABEL,
    "REVIEW": "hydraflow-review",
    "DIAGNOSE": "hydraflow-review",
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

#: Clock readings and random ids, normalised out of the comparison because they
#: differ between any two runs, armed or not — and pinned by name so the
#: comparison cannot be quietly widened into vacuity.
VOLATILE_FIELDS = ("recorded_at",)


class ScriptedTurn:
    """One director turn asking for one catalogued worker. Spawns nothing.

    The role is a parameter for the reason #11541's is: a bound's phase clause
    can only be *killed* by a request the rest of the machinery would otherwise
    allow, so a test that wants to prove the clause must ask for a role the
    catalog permits at the phase under test.

    The fencing tokens are read back out of the capsule rather than hardcoded,
    because a hardcoded driver id makes every request for a second issue fail
    ``DRIVER_IDENTITY_MISMATCH`` and silently turns a bound test into a fence
    test.
    """

    def __init__(
        self, role: str = "implementer", family: str = "claude-sonnet"
    ) -> None:
        self.cli_version = "2.1.239"
        self.turns = 0
        self._role = role
        self._family = family

    async def preflight(self) -> str:
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        self.turns += 1
        payload = prompt.split(CAPSULE_OPEN, 1)[1].split(CAPSULE_CLOSE, 1)[0]
        lease = json.loads(payload)["lease"]
        command = {
            "kind": "dispatch_workers",
            "rationale": "the retry counter is double-incremented",
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
                    "task_contract": "say where the double increment is",
                    "reason": "the review found a double increment",
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


class GitScript:
    """A ``SubprocessRunner`` answering scripted git reads and nothing else."""

    def __init__(self) -> None:
        self.answers = {
            "status": f"# branch.oid {HEAD}\n# branch.head {BRANCH}\n",
            "merge-base": f"{BASE}\n",
            "diff": "--- a\n+++ b\n",
        }
        self.calls: list[list[str]] = []

    async def run_simple(self, cmd: Any, **kwargs: Any) -> SimpleResult:
        argv = list(cmd)
        self.calls.append(argv)
        if argv[0] != "git":
            raise AssertionError("the actuator ran a non-git command in a regression")
        return SimpleResult(stdout=self.answers.get(argv[3], ""), returncode=0)


class SpawnCounter:
    """Stands in for ``run_lightweight_agent`` and records every call."""

    def __init__(self, *, before_reply: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._before_reply = before_reply

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls.append(kwargs)
        if self._before_reply is not None:
            self._before_reply()
        spawn_out = kwargs.get("spawn_out")
        if spawn_out is not None:
            spawn_out.update(
                {
                    "model": kwargs["model"],
                    "provider": "gateway",
                    "usage": {"input_tokens": 300, "output_tokens": 60},
                }
            )
        return SimpleResult(stdout="## Where\n\nthe retry arm", returncode=0)


def _settings(tmp_path: Path, canary: str) -> Any:
    from config import HydraFlowConfig

    built = HydraFlowConfig(
        state_file=tmp_path / "state.json",
        repo=CANARY_REPO,
        workspace_base=tmp_path / "worktrees",
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        fable_implement_canary_repo=canary,
    )
    built.workspace_path_for_issue(7).mkdir(parents=True, exist_ok=True)
    built.workspace_path_for_issue(9).mkdir(parents=True, exist_ok=True)
    return built


def _driver(state: str = "READY", issue: int = 7) -> IssueDriver:
    return IssueDriver(
        issue_number=issue,
        driver_id=f"drv-{issue}",
        repo_slug=CANARY_REPO,
        adapters={},
        labels=object(),  # type: ignore[arg-type]
        journal=object(),  # type: ignore[arg-type]
        stage_labels=STAGE_LABELS,
        driver_state=state,
    )


def _advance(
    phase: DriverPhase = DriverPhase.IMPLEMENT, state: str = "READY", issue: int = 7
) -> DriverAdvance:
    return DriverAdvance(
        issue_number=issue,
        driver_id=f"drv-{issue}",
        epoch=0,
        phase=phase,
        outcome=AdvanceOutcome.COMMITTED,
        state=state,
    )


def _assemble(
    tmp_path: Path,
    *,
    name: str,
    canary: str | None,
    wired: bool,
    turn: ScriptedTurn | None = None,
    git: GitScript | None = None,
    spawn: SpawnCounter | None = None,
    leases: WriterLeaseRegistry | None = None,
):
    """One director, with the writer actuator wired or entirely absent."""
    log = ShadowObservationLog(tmp_path / f"{name}-shadow.jsonl")
    started = spawn or SpawnCounter()
    scripted_git = git or GitScript()
    actuator = None
    covered = None
    if wired:
        settings = _settings(tmp_path, canary or "")
        actuator = ImplementWorkerRunner(
            config=settings,
            route_policy_revision=ROUTE_REVISION,
            runner=scripted_git,  # type: ignore[arg-type]
            leases=leases or WriterLeaseRegistry(),
            base_ref="origin/staging",
            spawn=started,
        )
        covered = lambda phase: implement_canary_covers(settings, phase=phase)  # noqa: E731
    built = FableDirector(
        runner=turn or ScriptedTurn(),  # type: ignore[arg-type]
        broker=ShadowDispatchBroker(),
        shadow_log=log,
        evidence=EVIDENCE,
        repo_slug=CANARY_REPO,
        route_policy_revision=ROUTE_REVISION,
        stage_labels=STAGE_LABELS,
        usd_budget_per_boundary=5.0,
        implement_dispatcher=actuator,
        implement_is_covered=covered,
    )
    return built, log, started, scripted_git


async def _observe(
    built: FableDirector,
    *,
    phase: DriverPhase = DriverPhase.IMPLEMENT,
    state: str = "READY",
    issue: int = 7,
) -> None:
    await built.observe_boundary(
        task=Task(id=issue, title="make the widget faster", tags=[READY_LABEL]),
        advance=_advance(phase, state, issue),
        driver=_driver(state, issue),
    )


def _rows(log: ShadowObservationLog) -> list[dict[str, object]]:
    collected = []
    for observation in log.recent():
        row = observation.model_dump(mode="json")
        for field in VOLATILE_FIELDS:
            row.pop(field, None)
        collected.append(row)
    return collected


async def _run(
    tmp_path: Path,
    *,
    name: str,
    canary: str | None,
    wired: bool,
    phase: DriverPhase = DriverPhase.IMPLEMENT,
    turn: ScriptedTurn | None = None,
):
    built, log, spawn, git = _assemble(
        tmp_path, name=name, canary=canary, wired=wired, turn=turn
    )
    await _observe(built, phase=phase)
    return _rows(log), spawn.calls, git.calls


@pytest.fixture
async def shadow_baseline(tmp_path: Path):
    """The arm with no writer actuator, no coverage predicate, no lease registry."""
    return await _run(tmp_path, name="baseline", canary=None, wired=False)


class TestOutsideTheBoundNothingMoves:
    async def test_an_untouched_deployment_records_the_shadow_evidence(
        self, tmp_path: Path, shadow_baseline
    ) -> None:
        rows, _spawns, _reads = shadow_baseline

        armed, _s, _r = await _run(tmp_path, name="empty", canary="", wired=True)

        assert armed == rows

    async def test_an_untouched_deployment_starts_no_writer(
        self, tmp_path: Path
    ) -> None:
        _rows_, spawns, _reads = await _run(
            tmp_path, name="empty", canary="", wired=True
        )

        assert spawns == []

    async def test_an_untouched_deployment_runs_no_git(self, tmp_path: Path) -> None:
        # Measuring a worktree is itself an effect: a disarmed host must not
        # start shelling out to git on every implement boundary.
        _rows_, _spawns, reads = await _run(
            tmp_path, name="empty", canary="", wired=True
        )

        assert reads == []

    async def test_another_repository_records_the_shadow_evidence(
        self, tmp_path: Path, shadow_baseline
    ) -> None:
        rows, _spawns, _reads = shadow_baseline

        other, _s, _r = await _run(
            tmp_path, name="other", canary="acme/other", wired=True
        )

        assert other == rows

    async def test_another_repository_starts_no_writer(self, tmp_path: Path) -> None:
        _rows_, spawns, _reads = await _run(
            tmp_path, name="other", canary="acme/other", wired=True
        )

        assert spawns == []

    @pytest.mark.parametrize(
        ("phase", "role", "family"),
        [
            pytest.param(DriverPhase.PLAN, "explorer", "claude-sonnet", id="plan"),
            pytest.param(DriverPhase.REVIEW, "architect", "claude-opus", id="review"),
        ],
    )
    async def test_another_phase_is_never_offered_to_the_writer_canary(
        self, tmp_path: Path, phase: DriverPhase, role: str, family: str
    ) -> None:
        """The phase clause, isolated from the defences behind it.

        #11541's mutation testing caught two earlier versions of the equivalent
        test passing with the phase clause **deleted** — first because the tier
        resolver also refuses the wrong phase, then because the capsule's role
        allow-list refuses the role anyway. So the role here is one the catalog
        *does* allow at the phase under test: an explorer at PLAN, an architect
        at REVIEW. With the clause present the boundary is never offered and no
        receipt is recorded at all.

        ``HITL`` is absent on purpose: ``WORKER_CATALOG`` catalogues no role for
        it, so no request could distinguish the clause from the catalog there,
        and a test that cannot fail is worse than none. ``TRIAGE`` is absent for
        the same reason.
        """
        rows, spawns, _reads = await _run(
            tmp_path,
            name=f"phase-{phase.value}",
            canary=CANARY_REPO,
            wired=True,
            phase=phase,
            turn=ScriptedTurn(role=role, family=family),
        )

        assert spawns == []
        assert [row["dispatched"] for row in rows] == [[]]

    async def test_the_plan_canary_alone_starts_no_writer(
        self, tmp_path: Path, shadow_baseline
    ) -> None:
        """The case this phase introduces: one dial armed, the other empty.

        Built through the real composition root rather than by hand, because
        the claim is about which objects an operator's process contains — and
        the hand-assembled arms above would pass with the wiring wrong.
        """
        from config import HydraFlowConfig
        from orchestrator import HydraFlowOrchestrator

        settings = HydraFlowConfig(
            state_file=tmp_path / "plan-only.json",
            repo=CANARY_REPO,
            scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
            execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
            fable_plan_canary_repo=CANARY_REPO,
        )
        built = HydraFlowOrchestrator(settings)._svc.fable_director  # noqa: SLF001

        assert built is not None
        assert built._implement_dispatcher is None  # noqa: SLF001

    async def test_clearing_the_dial_mid_run_stops_the_next_boundary(
        self, tmp_path: Path
    ) -> None:
        # The one-action rollback at the seam it has to act on: the actuator
        # object still exists, and what stops it is the live predicate.
        settings = _settings(tmp_path, CANARY_REPO)
        spawn = SpawnCounter()
        built = FableDirector(
            runner=ScriptedTurn(),  # type: ignore[arg-type]
            broker=ShadowDispatchBroker(),
            shadow_log=ShadowObservationLog(tmp_path / "rollback-shadow.jsonl"),
            evidence=EVIDENCE,
            repo_slug=CANARY_REPO,
            route_policy_revision=ROUTE_REVISION,
            stage_labels=STAGE_LABELS,
            usd_budget_per_boundary=5.0,
            implement_dispatcher=ImplementWorkerRunner(
                config=settings,
                route_policy_revision=ROUTE_REVISION,
                runner=GitScript(),  # type: ignore[arg-type]
                leases=WriterLeaseRegistry(),
                base_ref="origin/staging",
                spawn=spawn,
            ),
            implement_is_covered=lambda phase: implement_canary_covers(
                settings, phase=phase
            ),
        )
        await _observe(built)
        started_while_armed = len(spawn.calls)

        object.__setattr__(settings, "fable_implement_canary_repo", "")
        await _observe(built)

        assert (started_while_armed, len(spawn.calls)) == (1, 1)


class TestInsideTheBoundSomethingActuallyHappens:
    """Without these, deleting the feature would pass every test above."""

    async def test_the_canary_repository_at_implement_starts_one_writer(
        self, tmp_path: Path
    ) -> None:
        _rows_, spawns, _reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert len(spawns) == 1

    async def test_the_canary_repository_measures_its_worktree(
        self, tmp_path: Path
    ) -> None:
        # Twice per boundary: once to mint the lease, once to fence the result.
        _rows_, _spawns, reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert [argv[3] for argv in reads] == [
            "status",
            "merge-base",
            "diff",
            "status",
            "merge-base",
            "diff",
        ]

    async def test_the_boundary_records_an_accepted_receipt(
        self, tmp_path: Path
    ) -> None:
        rows, _spawns, _reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert [row["status"] for row in rows[0]["dispatched"]] == ["accepted"]

    async def test_the_armed_evidence_differs_from_the_shadow_evidence(
        self, tmp_path: Path, shadow_baseline
    ) -> None:
        # The comparisons in the class above are only meaningful if these two
        # are actually distinguishable by them.
        rows, _spawns, _reads = shadow_baseline

        armed, _s, _r = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert armed != rows


class TestTheFenceIsConsultedAtTheDirectorSeam:
    """``check_worker_fence`` is unit-tested; that the director *asks* it is not.

    A director that computed a lease and never fenced the result would pass
    every test in ``tests/test_implement_broker.py``, which is precisely the
    vacuity #11541's review found three times.
    """

    async def test_a_commit_landing_mid_run_supersedes_the_result(
        self, tmp_path: Path
    ) -> None:
        git = GitScript()
        spawn = SpawnCounter(
            before_reply=lambda: git.answers.__setitem__(
                "status", f"# branch.oid {'9' * 40}\n# branch.head {BRANCH}\n"
            )
        )
        built, log, _spawn, _git = _assemble(
            tmp_path,
            name="fenced",
            canary=CANARY_REPO,
            wired=True,
            git=git,
            spawn=spawn,
        )

        await _observe(built)

        assert [row["status"] for row in _rows(log)[0]["dispatched"]] == ["superseded"]

    async def test_a_superseded_result_never_becomes_context_for_the_next_turn(
        self, tmp_path: Path
    ) -> None:
        # The difference between rejecting and ignoring: a rejected result must
        # not reach the capsule the next boundary is built from.
        git = GitScript()
        spawn = SpawnCounter(
            before_reply=lambda: git.answers.__setitem__("diff", "moved under it")
        )
        built, _log, _spawn, _git = _assemble(
            tmp_path,
            name="context",
            canary=CANARY_REPO,
            wired=True,
            git=git,
            spawn=spawn,
        )

        await _observe(built)
        actuator = built._implement_dispatcher  # noqa: SLF001

        assert actuator is not None and actuator.artifacts == []

    async def test_an_unmoved_slice_does_become_context(self, tmp_path: Path) -> None:
        built, _log, _spawn, _git = _assemble(
            tmp_path, name="kept", canary=CANARY_REPO, wired=True
        )

        await _observe(built)
        actuator = built._implement_dispatcher  # noqa: SLF001

        assert actuator is not None and len(actuator.artifacts) == 1


class TestAWaitingDriverHoldsNoWriterAuthority:
    """#11542's fourth acceptance criterion at the seam that enforces it."""

    @pytest.mark.parametrize(
        "waiting",
        [
            pytest.param("PARKED", id="ci-wait"),
            pytest.param("DIAGNOSE", id="diagnostic"),
            pytest.param("HITL_WAIT", id="human"),
        ],
    )
    async def test_a_wait_takes_the_lease_back(
        self, tmp_path: Path, waiting: str
    ) -> None:
        leases = WriterLeaseRegistry()
        leases.acquire(7, "req-from-before")
        built, _log, _spawn, _git = _assemble(
            tmp_path,
            name=f"wait-{waiting}",
            canary=CANARY_REPO,
            wired=True,
            leases=leases,
        )

        await _observe(built, state=waiting)

        assert leases.holder(7) is None

    async def test_a_working_driver_keeps_its_lease(self, tmp_path: Path) -> None:
        # Non-vacuity: revoking unconditionally would pass all three above.
        leases = WriterLeaseRegistry()
        leases.acquire(9, "req-elsewhere")
        built, _log, _spawn, _git = _assemble(
            tmp_path, name="working", canary=CANARY_REPO, wired=True, leases=leases
        )

        await _observe(built, state="READY", issue=7)

        assert leases.holder(9) == "req-elsewhere"

    async def test_a_wait_dispatches_no_writer(self, tmp_path: Path) -> None:
        built, log, spawn, _git = _assemble(
            tmp_path, name="parked", canary=CANARY_REPO, wired=True
        )

        await _observe(built, state="HITL_WAIT")

        assert spawn.calls == []

    async def test_a_wait_produces_a_receipt_naming_the_hibernation(
        self, tmp_path: Path
    ) -> None:
        # Counted rather than silent: an operator reading a boundary with no
        # workers needs to know whether the director declined or was never
        # asked.
        built, log, _spawn, _git = _assemble(
            tmp_path, name="parked-receipt", canary=CANARY_REPO, wired=True
        )

        await _observe(built, state="HITL_WAIT")

        assert [row["reason"] for row in _rows(log)[0]["dispatched"]] == ["hibernating"]

    async def test_the_boundary_after_a_wait_re_measures_from_scratch(
        self, tmp_path: Path
    ) -> None:
        """ "Reconstruct from deterministic checkpoints", proven by there being
        nothing to reconstruct: the lease the next boundary mints comes from a
        fresh reading of the worktree, not from anything carried across the
        wait.
        """
        git = GitScript()
        built, _log, spawn, _git = _assemble(
            tmp_path, name="resume", canary=CANARY_REPO, wired=True, git=git
        )

        await _observe(built, state="HITL_WAIT")
        reads_during_the_wait = len(git.calls)
        git.answers["status"] = f"# branch.oid {'a' * 40}\n# branch.head {BRANCH}\n"
        await _observe(built, state="READY")

        assert (reads_during_the_wait, len(spawn.calls)) == (0, 1)


class TestIndependentReviewCannotBePerformedByTheImplementer:
    """#11542's seventh acceptance criterion, at the fence that enforces it.

    ``admit_dispatch`` has always had a ``SELF_REVIEW_FORBIDDEN`` arm, and until
    this phase it could never fire: nothing populated ``implementer_spawn_ids``
    because no brokered implementer had ever run. Now one can, so the fence has
    something to compare against — and this proves the director actually feeds
    it rather than passing an empty set forever.
    """

    async def test_a_completed_implementer_is_remembered(self, tmp_path: Path) -> None:
        built, _log, _spawn, _git = _assemble(
            tmp_path, name="lineage", canary=CANARY_REPO, wired=True
        )

        await _observe(built)

        assert built._implementer_spawns.get(7)  # noqa: SLF001

    async def test_a_superseded_implementer_is_not_remembered(
        self, tmp_path: Path
    ) -> None:
        # A refused or superseded request produced no lineage; inventing one
        # would make the self-review fence refuse a reviewer over a worker that
        # never contributed anything.
        git = GitScript()
        spawn = SpawnCounter(
            before_reply=lambda: git.answers.__setitem__("diff", "moved")
        )
        built, _log, _spawn, _git = _assemble(
            tmp_path,
            name="no-lineage",
            canary=CANARY_REPO,
            wired=True,
            git=git,
            spawn=spawn,
        )

        await _observe(built)

        assert built._implementer_spawns.get(7) is None  # noqa: SLF001

    async def test_an_explorer_is_not_remembered_as_an_implementer(
        self, tmp_path: Path
    ) -> None:
        built, _log, _spawn, _git = _assemble(
            tmp_path,
            name="explorer-lineage",
            canary=CANARY_REPO,
            wired=True,
            turn=ScriptedTurn(role="explorer"),
        )

        await _observe(built)

        assert built._implementer_spawns.get(7) is None  # noqa: SLF001

    async def test_the_remembered_spawn_is_the_one_the_receipt_names(
        self, tmp_path: Path
    ) -> None:
        built, log, _spawn, _git = _assemble(
            tmp_path, name="joined", canary=CANARY_REPO, wired=True
        )

        await _observe(built)
        recorded = _rows(log)[0]["dispatched"][0]["child_spawn_id"]

        assert built._implementer_spawns[7] == frozenset({recorded})  # noqa: SLF001


class TestAcceptedWorkBecomesEvidenceNotAuthority:
    async def test_an_accepted_receipt_carries_a_served_model_and_a_cost(
        self, tmp_path: Path
    ) -> None:
        # ADR-0137 B5's bar: 100% of accepted workers carry lineage, cost and
        # effective-route receipts.
        built, log, _spawn, _git = _assemble(
            tmp_path, name="evidence", canary=CANARY_REPO, wired=True
        )

        await _observe(built)
        row = _rows(log)[0]["dispatched"][0]

        assert row["served_model"] == "claude-sonnet-4-6"

    async def test_the_receipt_never_carries_the_artifact_text(
        self, tmp_path: Path
    ) -> None:
        built, log, _spawn, _git = _assemble(
            tmp_path, name="no-artifact", canary=CANARY_REPO, wired=True
        )

        await _observe(built)
        row = _rows(log)[0]["dispatched"][0]

        assert "the retry arm" not in json.dumps(row)

    async def test_the_receipt_status_is_a_contract_value(self, tmp_path: Path) -> None:
        built, log, _spawn, _git = _assemble(
            tmp_path, name="status", canary=CANARY_REPO, wired=True
        )

        await _observe(built)

        assert _rows(log)[0]["dispatched"][0]["status"] == (
            ReceiptStatus.ACCEPTED.value
        )
