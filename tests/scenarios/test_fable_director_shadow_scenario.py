"""MockWorld scenario: the shadow director watching a real driver boundary (#11537).

The unit tests prove each piece against doubles. This proves the *integration* —
the one thing neither the unit layer nor an architecture guard can see: that
attaching a shadow director to a live allocator, over ``FakeGitHub``'s real
``PRPort`` surface and a real ``IssueStore``-shaped queue and a real journal
file, leaves the pipeline doing exactly what it did without one.

So the scenario runs the *same* boundary twice, once observed and once not, and
compares what reached the world: the labels ``swap_pipeline_labels`` actually
left behind, the planner's call log, the journal's committed keys, and the tick
report the loop acts on. The director meanwhile writes a full comparison record
including a hypothetical worker tree — which is the point of it existing, and
also what makes the equality above non-vacuous.

No ``AsyncMock`` of a port anywhere. The one double is the director's *turn*,
which is scripted rather than spawned: spawning a real CLI is what the air-gap
seam forbids, and ``director_turn_runner`` is declared ``config_disable`` for
exactly that reason.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from director_broker import ShadowDispatchBroker
from director_sandbox import ProbeEvidence
from director_shadow_log import ShadowAgreement, ShadowObservationLog, TurnFailure
from director_turn_runner import CAPSULE_CLOSE, CAPSULE_OPEN, DirectorTurnResult
from driver_contracts import DriverPhase
from driver_journal import DriverJournal
from driver_manager import DriverManager, PipelineLabelAdapter
from driver_ownership import DriverOwnershipRegistry
from driver_phase_adapters import PlanPhaseAdapter
from fable_director import FableDirector
from models import PlanResult, Task
from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario

# Two issue numbers, one per arm of the differential run: FakeGitHub's label
# state is real state, so re-running the same boundary on the same issue would
# start the second arm from the first arm's outcome.
ISSUE_BASELINE = 8811
ISSUE_SHADOWED = 8812
FIND_LABEL = "hydraflow-find"
PLAN_LABEL = "hydraflow-plan"
READY_LABEL = "hydraflow-ready"
REVIEW_LABEL = "hydraflow-review"
HITL_LABEL = "hydraflow-hitl"

ORDERED_LABELS = (FIND_LABEL, PLAN_LABEL, READY_LABEL, REVIEW_LABEL, HITL_LABEL)
STAGE_LABELS = {
    "TRIAGE": FIND_LABEL,
    "PLAN": PLAN_LABEL,
    "READY": READY_LABEL,
    "REVIEW": REVIEW_LABEL,
    "DIAGNOSE": REVIEW_LABEL,
    "HITL_WAIT": HITL_LABEL,
    "HITL_APPLY": HITL_LABEL,
}

ROUTE_REVISION = "route-scenario-1"
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


class PortBackedPlanner:
    """A planner that does to the world what the real one does: swap the label."""

    def __init__(self, github: object) -> None:
        self._github = github
        self.planned: list[int] = []

    async def plan_single_issue(self, issue: Task, *, semaphore: object = None):
        self.planned.append(issue.id)
        await self._github.swap_pipeline_labels(issue.id, READY_LABEL)
        return PlanResult(issue_number=issue.id, success=True, summary="planned")


class SingleIssueStore:
    """A store that offers one plannable issue, then nothing."""

    def __init__(self, task: Task) -> None:
        self._pending = [task]
        self.released: list[int] = []
        self.requeued: list[tuple[int, str]] = []

    def get_plannable(self, max_count: int) -> list[Task]:
        taken, self._pending = self._pending[:max_count], self._pending[max_count:]
        return taken

    def get_implementable(self, max_count: int) -> list[Task]:
        return []

    def get_reviewable(self, max_count: int) -> list[Task]:
        return []

    def release_in_flight(
        self, issue_numbers: set[int], *, expected_stage: str | None = None
    ) -> None:
        self.released.extend(sorted(issue_numbers))

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        self.requeued.append((task.id, next_stage))


class ScriptedTurnRunner:
    """One scripted director turn. Spawns nothing — the real runner is seamed."""

    def __init__(self, command: dict[str, Any]) -> None:
        self._command = command
        self.cli_version = "2.1.239"
        self.turns = 0

    async def preflight(self) -> str:
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        """Answer from the capsule, the way a real director has to.

        The driver id, epoch and phase attempt are read back out of the capsule
        rather than hardcoded — which is the whole fencing contract in
        miniature. A scripted answer with a made-up driver id would be refused
        with ``DRIVER_IDENTITY_MISMATCH`` and the scenario would prove only that
        the fence works, never that an honest request survives it.
        """
        self.turns += 1
        payload = prompt.split(CAPSULE_OPEN, 1)[1].split(CAPSULE_CLOSE, 1)[0]
        lease = json.loads(payload)["lease"]
        command = json.loads(json.dumps(self._command))
        for dispatch in command["dispatches"]:
            dispatch["driver_id"] = lease["driver_id"]
            dispatch["epoch"] = lease["epoch"]
            dispatch["phase_attempt"] = lease["phase_attempt"]
        self._command = command
        return DirectorTurnResult(
            frames=[
                CLEAN_INIT,
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": json.dumps(self._command)}]
                    },
                },
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "total_cost_usd": 0.017,
                },
            ],
            exit_code=0,
            usd_cost=0.017,
            latency_ms=880,
        )


def _explorer_command() -> dict[str, Any]:
    """A director asking for one read-only explorer at the plan boundary."""
    return {
        "kind": "dispatch_workers",
        "rationale": "the plan needs the module map first",
        "dispatches": [
            {
                "request_id": "req-explore-1",
                "driver_id": "PLACEHOLDER",
                "epoch": 0,
                "phase_attempt": 0,
                "worker_role": "explorer",
                "model_requirement": {
                    "kind": "literal_family",
                    "value": "claude-sonnet",
                },
                "task_contract": "map the modules this issue touches",
                "reason": "the plan needs the module map first",
                "expected_route_policy_revision": ROUTE_REVISION,
                "idempotency_key": "key-explore-1",
            }
        ],
    }


def _build(mock_world, tmp_path, *, name: str, issue: int, with_director: bool):
    """One allocator over the real ports, with or without a shadow director."""
    github = mock_world.github
    planner = PortBackedPlanner(github)
    store = SingleIssueStore(Task(id=issue, title="driven issue", tags=[PLAN_LABEL]))
    journal_path = tmp_path / f"{name}-driver_journal.jsonl"
    director = None
    shadow_log = None
    if with_director:
        shadow_log = ShadowObservationLog(tmp_path / f"{name}-shadow.jsonl")
        director = FableDirector(
            runner=ScriptedTurnRunner(_explorer_command()),  # type: ignore[arg-type]
            broker=ShadowDispatchBroker(),
            shadow_log=shadow_log,
            evidence=EVIDENCE,
            repo_slug="acme/widgets",
            route_policy_revision=ROUTE_REVISION,
            stage_labels=STAGE_LABELS,
            usd_budget_per_boundary=5.0,
        )
    manager = DriverManager(
        store=store,
        labels=PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS),
        journal=DriverJournal(journal_path),
        ownership=DriverOwnershipRegistry(enabled=True),
        adapters={DriverPhase.PLAN: PlanPhaseAdapter(planner, ready_label=READY_LABEL)},
        stage_labels=STAGE_LABELS,
        repo_slug="acme/widgets",
        max_in_flight=1,
        stage_caps={DriverPhase.PLAN: 1},
        observer=director,
    )
    return manager, github, planner, store, journal_path, shadow_log


async def _run(mock_world, tmp_path, *, name: str, issue: int, with_director: bool):
    """Drive the plan boundary and collect every effect that reached the world.

    The issue number is normalised out of the collected effects so the two arms
    stay comparable. They run on *different* issues on purpose: FakeGitHub's
    label set is real state, so re-running the same boundary on the same issue
    would start the second arm from the first arm's outcome and compare nothing.
    """
    manager, github, planner, store, journal_path, shadow_log = _build(
        mock_world, tmp_path, name=name, issue=issue, with_director=with_director
    )
    report = await manager.tick()
    effects = {
        "labels": sorted(await github.get_issue_labels(issue)),
        "planned": [n - issue for n in planner.planned],
        "released": [n - issue for n in store.released],
        "requeued": [(n - issue, stage) for n, stage in store.requeued],
        # A count, not the keys: a boundary key carries the driver's random id.
        "committed_boundaries": len(DriverJournal(journal_path).committed_keys(issue)),
        "admitted": tuple(n - issue for n in report.admitted),
        "advanced": [
            (a.issue_number - issue, a.outcome.value, a.state) for a in report.advanced
        ],
    }
    return effects, shadow_log


@pytest.fixture
def seeded_issues(mock_world):
    for issue in (ISSUE_BASELINE, ISSUE_SHADOWED):
        IssueBuilder().numbered(issue).titled("driven issue").labeled(PLAN_LABEL).at(
            mock_world
        )
    return mock_world


async def _shadowed(mock_world, tmp_path):
    return await _run(
        mock_world,
        tmp_path,
        name="shadowed",
        issue=ISSUE_SHADOWED,
        with_director=True,
    )


class TestTheShadowDirectorChangesNothingThroughTheRealPorts:
    """The differential proof, this time with FakeGitHub behind a real PRPort."""

    async def test_the_labels_left_on_github_are_the_same(
        self, seeded_issues, tmp_path
    ) -> None:
        baseline, _ = await _run(
            seeded_issues,
            tmp_path,
            name="baseline",
            issue=ISSUE_BASELINE,
            with_director=False,
        )

        shadowed, _ = await _shadowed(seeded_issues, tmp_path)

        assert shadowed["labels"] == baseline["labels"]

    async def test_every_other_live_effect_is_the_same(
        self, seeded_issues, tmp_path
    ) -> None:
        baseline, _ = await _run(
            seeded_issues,
            tmp_path,
            name="baseline",
            issue=ISSUE_BASELINE,
            with_director=False,
        )

        shadowed, _ = await _shadowed(seeded_issues, tmp_path)

        assert shadowed == baseline


class TestTheShadowDirectorRecordsWhatItWouldHaveDone:
    """…and that it really ran, so the equality above is not vacuous."""

    async def test_the_boundary_produces_one_observation(
        self, seeded_issues, tmp_path
    ) -> None:
        _effects, shadow_log = await _shadowed(seeded_issues, tmp_path)

        assert shadow_log.summary()["observations"] == 1

    async def test_the_hypothetical_worker_tree_names_the_requested_role(
        self, seeded_issues, tmp_path
    ) -> None:
        _effects, shadow_log = await _shadowed(seeded_issues, tmp_path)

        assert shadow_log.recent()[0].would_dispatch[0]["role"] == "explorer"

    async def test_no_worker_in_the_tree_was_dispatched(
        self, seeded_issues, tmp_path
    ) -> None:
        _effects, shadow_log = await _shadowed(seeded_issues, tmp_path)

        assert shadow_log.recent()[0].would_dispatch[0]["dispatched"] is False

    async def test_the_turn_is_recorded_as_having_succeeded(
        self, seeded_issues, tmp_path
    ) -> None:
        _effects, shadow_log = await _shadowed(seeded_issues, tmp_path)

        assert shadow_log.recent()[0].turn_failure is TurnFailure.NONE

    async def test_the_director_agrees_with_the_committed_boundary(
        self, seeded_issues, tmp_path
    ) -> None:
        # The controller committed the plan boundary; the director asked for
        # workers to do that work. That is agreement.
        _effects, shadow_log = await _shadowed(seeded_issues, tmp_path)

        assert shadow_log.recent()[0].agreement is ShadowAgreement.AGREED

    async def test_the_comparison_survives_a_restart_of_the_log(
        self, seeded_issues, tmp_path
    ) -> None:
        # The rollup an operator watches is seeded from disk, so a factory
        # restart does not reset the numbers mid-canary.
        _effects, shadow_log = await _shadowed(seeded_issues, tmp_path)

        reloaded = ShadowObservationLog(shadow_log.path)

        assert reloaded.summary()["observations"] == 1
