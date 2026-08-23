"""MockWorld scenario: a brokered Sonnet and Opus Plan turn, end to end (#11541).

The unit tests prove each piece against doubles. This proves the *integration* —
what neither the unit layer nor an architecture guard can see:

* the whole chain runs through the **real** seams. A real ``DriverManager``
  allocator, a real ``IssueDriver`` boundary, a real ``ShadowDispatchBroker``
  admission, a real ``PlanWorkerRunner``, and the real
  ``runner_utils.run_lightweight_agent`` spawn seam — including the real
  per-spawn ``resolve_harness_env`` mint, the real env scrub and the real
  revoke. The only doubles are at the ports: ``FakeGitHub`` behind the real
  ``PRPort``, a store-shaped queue, a recording gateway control plane, and a
  subprocess runner that answers with a CLI result envelope instead of
  spawning. **No ``AsyncMock`` of a port anywhere**;
* the brokered plan and a Classic plan reach the **same canonical label
  outcome**, because the canary adds workers beside the deterministic phase and
  takes no authority from it;
* each child really does get its own short-lived key, and each key is really
  revoked — the two halves of "its own short-lived key" that a unit test with an
  injected spawn cannot see.

The director's *turn* is scripted rather than spawned: spawning a real CLI is
what the air-gap seam forbids, and ``director_turn_runner`` is ``config_disable``
for exactly that reason. Everything downstream of the turn is real.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from director_broker import ShadowDispatchBroker
from director_sandbox import ProbeEvidence
from director_shadow_log import ShadowObservationLog
from director_turn_runner import CAPSULE_CLOSE, CAPSULE_OPEN, DirectorTurnResult
from driver_contracts import DriverPhase
from driver_journal import DriverJournal
from driver_manager import DriverManager, PipelineLabelAdapter
from driver_ownership import DriverOwnershipRegistry
from driver_phase_adapters import PlanPhaseAdapter
from fable_director import FableDirector
from gateway_mint_client import GatewayMintCredential
from models import PlanResult, Task
from plan_broker import PlanCanaryLatch, plan_canary_covers
from plan_worker_runner import PlanWorkerRunner
from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario

CANARY_REPO = "acme/widgets"
ISSUE_CLASSIC = 8821
ISSUE_BROKERED = 8822
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
    """The deterministic plan phase: it swaps the label, exactly as the real one."""

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


class RecordingGatewayControlPlane:
    """The real control-plane contract, recording every mint and revoke."""

    def __init__(self) -> None:
        self.minted: list[Any] = []
        self.revoked: list[str] = []
        self._n = 0

    async def mint_key(
        self, *, base_url, control_token, request
    ) -> GatewayMintCredential:
        _ = (base_url, control_token)
        self._n += 1
        self.minted.append(request)
        return GatewayMintCredential(
            key_id=f"key-{self._n}",
            token=f"hfgw_virtual_{self._n}",
            expires_at="2099-08-22T12:05:00Z",
        )

    async def revoke_key(self, *, base_url, control_token, key_id) -> bool:
        _ = (base_url, control_token)
        self.revoked.append(key_id)
        return True


class EnvelopeRunner:
    """A SubprocessRunner that answers with the CLI's one-shot JSON envelope.

    Not a mock of a port: it is the process boundary, and it returns exactly the
    shape ``_unwrap_result_envelope`` parses, so the real seam's unwrapping,
    usage extraction and credit scan all run.
    """

    def __init__(self) -> None:
        self.spawns: list[dict[str, Any]] = []

    async def run_simple(self, cmd, *, env=None, input=None, timeout=None, cwd=None):  # noqa: A002
        from execution import SimpleResult

        self.spawns.append({"cmd": list(cmd), "env": dict(env or {})})
        envelope = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "## Modules\n\nthe module map",
            "session_id": "sess-1",
            "usage": {"input_tokens": 1200, "output_tokens": 300},
        }
        return SimpleResult(stdout=json.dumps(envelope), returncode=0)


class ScriptedTurnRunner:
    """One scripted director turn asking for a Sonnet planner and an Opus judge."""

    def __init__(self) -> None:
        self.cli_version = "2.1.239"
        self.turns = 0

    async def preflight(self) -> str:
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        """Answer *from the capsule*, the way a real director has to.

        The fencing tokens are read back out of the capsule rather than
        hardcoded; a made-up driver id would be refused with
        ``DRIVER_IDENTITY_MISMATCH`` and this scenario would prove only that the
        fence works, never that an honest request survives it.
        """
        self.turns += 1
        payload = prompt.split(CAPSULE_OPEN, 1)[1].split(CAPSULE_CLOSE, 1)[0]
        capsule = json.loads(payload)
        lease = capsule["lease"]
        command = {
            "kind": "dispatch_workers",
            "rationale": "map the modules, then judge the shape",
            "dispatches": [
                _dispatch(lease, "planner", "claude-sonnet", 1),
                _dispatch(lease, "architect", "claude-opus", 2),
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
                    "total_cost_usd": 0.02,
                },
            ],
            exit_code=0,
            usd_cost=0.02,
            latency_ms=900,
        )


def _dispatch(lease: dict[str, Any], role: str, family: str, n: int) -> dict[str, Any]:
    return {
        "request_id": f"req-{n}",
        "driver_id": lease["driver_id"],
        "epoch": lease["epoch"],
        "phase_attempt": lease["phase_attempt"],
        "worker_role": role,
        "model_requirement": {"kind": "literal_family", "value": family},
        "task_contract": f"do the {role}'s part of the plan",
        "reason": "the plan needs it",
        "expected_route_policy_revision": ROUTE_REVISION,
        "idempotency_key": f"key-{n}",
    }


def _config(tmp_path, *, canary: str):
    from config import HydraFlowConfig
    from scheduling_model import ExecutionRuntime, SchedulingModel

    return HydraFlowConfig(
        state_file=tmp_path / "state.json",
        repo=CANARY_REPO,
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        fable_plan_canary_repo=canary,
        gateway_base_url="http://gateway.test:8080",
    )


def _build(mock_world, tmp_path, *, name: str, issue: int, canary: str | None):
    """One allocator over the real ports, with or without an armed canary."""
    github = mock_world.github
    planner = PortBackedPlanner(github)
    store = SingleIssueStore(Task(id=issue, title="driven issue", tags=[PLAN_LABEL]))
    director = None
    shadow_log = None
    control = RecordingGatewayControlPlane()
    spawner = EnvelopeRunner()
    if canary is not None:
        config = _config(tmp_path, canary=canary)
        shadow_log = ShadowObservationLog(tmp_path / f"{name}-shadow.jsonl")
        director = FableDirector(
            runner=ScriptedTurnRunner(),  # type: ignore[arg-type]
            broker=ShadowDispatchBroker(),
            shadow_log=shadow_log,
            evidence=EVIDENCE,
            repo_slug=CANARY_REPO,
            route_policy_revision=ROUTE_REVISION,
            stage_labels=STAGE_LABELS,
            usd_budget_per_boundary=5.0,
            dispatcher=PlanWorkerRunner(
                config=config,
                route_policy_revision=ROUTE_REVISION,
                runner=spawner,  # type: ignore[arg-type]
                gateway_client=control,  # type: ignore[arg-type]
            ),
            is_covered=lambda phase: plan_canary_covers(config, phase=phase),
            latch=PlanCanaryLatch(ttl_seconds=900),
        )
    manager = DriverManager(
        store=store,
        labels=PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS),
        journal=DriverJournal(tmp_path / f"{name}-driver_journal.jsonl"),
        ownership=DriverOwnershipRegistry(enabled=True),
        adapters={DriverPhase.PLAN: PlanPhaseAdapter(planner, ready_label=READY_LABEL)},
        stage_labels=STAGE_LABELS,
        repo_slug=CANARY_REPO,
        max_in_flight=1,
        stage_caps={DriverPhase.PLAN: 1},
        observer=director,
    )
    return manager, github, planner, shadow_log, control, spawner


async def _run(mock_world, tmp_path, *, name, issue, canary):
    built = _build(mock_world, tmp_path, name=name, issue=issue, canary=canary)
    manager, github, planner, shadow_log, control, spawner = built
    await manager.tick()
    outcome = {
        "labels": sorted(await github.get_issue_labels(issue)),
        "planned": [n - issue for n in planner.planned],
    }
    return outcome, shadow_log, control, spawner


@pytest.fixture
def seeded_issues(mock_world, monkeypatch):
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    for issue in (ISSUE_CLASSIC, ISSUE_BROKERED):
        IssueBuilder().numbered(issue).titled("driven issue").labeled(PLAN_LABEL).at(
            mock_world
        )
    return mock_world


async def _brokered(mock_world, tmp_path):
    return await _run(
        mock_world,
        tmp_path,
        name="brokered",
        issue=ISSUE_BROKERED,
        canary=CANARY_REPO,
    )


class TestABrokeredPlanReachesTheSameOutcomeAsAClassicOne:
    """The gates stay authoritative: the canary adds workers, not authority."""

    async def test_the_labels_left_on_github_are_the_same(
        self, seeded_issues, tmp_path
    ) -> None:
        classic, _log, _c, _s = await _run(
            seeded_issues, tmp_path, name="classic", issue=ISSUE_CLASSIC, canary=None
        )

        brokered, _log2, _c2, _s2 = await _brokered(seeded_issues, tmp_path)

        assert brokered["labels"] == classic["labels"]

    async def test_the_deterministic_plan_phase_still_ran(
        self, seeded_issues, tmp_path
    ) -> None:
        # Plan validation, the constitution gate and the cohort gate all live
        # inside that phase. A canary that skipped it would have taken the
        # authority the acceptance criteria say it must not.
        brokered, _log, _c, _s = await _brokered(seeded_issues, tmp_path)

        assert brokered["planned"] == [0]


class TestEachBrokeredChildIsItsOwnProcessWithItsOwnKey:
    async def test_two_children_are_spawned(self, seeded_issues, tmp_path) -> None:
        _o, _log, _control, spawner = await _brokered(seeded_issues, tmp_path)

        assert len(spawner.spawns) == 2

    async def test_a_sonnet_planner_and_an_opus_architect_both_ran(
        self, seeded_issues, tmp_path
    ) -> None:
        _o, _log, _control, spawner = await _brokered(seeded_issues, tmp_path)

        models = " ".join(" ".join(s["cmd"]) for s in spawner.spawns)
        assert "sonnet" in models
        assert "opus" in models

    async def test_each_child_minted_its_own_key(self, seeded_issues, tmp_path) -> None:
        _o, _log, control, _s = await _brokered(seeded_issues, tmp_path)

        assert len(control.minted) == 2

    async def test_no_two_children_share_a_spawn_id(
        self, seeded_issues, tmp_path
    ) -> None:
        _o, _log, control, _s = await _brokered(seeded_issues, tmp_path)

        assert len({request.spawn_id for request in control.minted}) == 2

    async def test_each_child_is_attributed_to_its_own_role(
        self, seeded_issues, tmp_path
    ) -> None:
        _o, _log, control, _s = await _brokered(seeded_issues, tmp_path)

        assert {request.principal_id for request in control.minted} == {
            "planner",
            "architect",
        }

    async def test_every_key_was_revoked(self, seeded_issues, tmp_path) -> None:
        # Short-lived is only half of it; the lease is closed when the child
        # finishes rather than left to its TTL.
        _o, _log, control, _s = await _brokered(seeded_issues, tmp_path)

        assert sorted(control.revoked) == ["key-1", "key-2"]

    async def test_no_child_receives_the_control_token(
        self, seeded_issues, tmp_path
    ) -> None:
        _o, _log, _control, spawner = await _brokered(seeded_issues, tmp_path)

        assert all(
            "HYDRAFLOW_GATEWAY_CONTROL_TOKEN" not in spawn["env"]
            for spawn in spawner.spawns
        )

    async def test_each_child_receives_its_own_virtual_token(
        self, seeded_issues, tmp_path
    ) -> None:
        _o, _log, _control, spawner = await _brokered(seeded_issues, tmp_path)

        tokens = {spawn["env"].get("ANTHROPIC_AUTH_TOKEN") for spawn in spawner.spawns}
        assert tokens == {"hfgw_virtual_1", "hfgw_virtual_2"}


class TestTheEvidenceIsComplete:
    async def test_every_child_carries_a_receipt(self, seeded_issues, tmp_path) -> None:
        _o, log, _c, _s = await _brokered(seeded_issues, tmp_path)

        assert len(log.recent()[0].dispatched) == 2

    async def test_every_receipt_names_the_model_that_served_it(
        self, seeded_issues, tmp_path
    ) -> None:
        _o, log, _c, _s = await _brokered(seeded_issues, tmp_path)

        served = {row["served_model"] for row in log.recent()[0].dispatched}
        assert all(model and "claude" in model for model in served)

    async def test_every_receipt_carries_a_child_spawn_id(
        self, seeded_issues, tmp_path
    ) -> None:
        _o, log, _c, _s = await _brokered(seeded_issues, tmp_path)

        assert all(row["child_spawn_id"] for row in log.recent()[0].dispatched)

    async def test_the_rollup_stops_calling_itself_shadow_mode(
        self, seeded_issues, tmp_path
    ) -> None:
        _o, log, _c, _s = await _brokered(seeded_issues, tmp_path)

        summary = log.summary()
        assert (summary["workers_dispatched"], summary["shadow_mode"]) == (2, False)

    async def test_a_classic_run_records_no_evidence_at_all(
        self, seeded_issues, tmp_path
    ) -> None:
        # Non-vacuity in the other direction: without the canary there is no
        # shadow log to read, so the assertions above are about something the
        # canary actually did.
        _o, log, control, spawner = await _run(
            seeded_issues, tmp_path, name="classic", issue=ISSUE_CLASSIC, canary=None
        )

        assert (log, control.minted, spawner.spawns) == (None, [], [])
