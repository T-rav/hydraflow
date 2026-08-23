"""MockWorld scenario: a fenced Sonnet implementer, end to end (#11542).

The unit tests prove each piece against doubles. This proves the *integration* —
what neither the unit layer nor an architecture guard can see:

* the whole chain runs through the **real** seams. A real ``DriverManager``
  allocator, a real ``IssueDriver`` boundary, a real ``ImplementPhaseAdapter``
  over the deterministic implementer, a real ``ShadowDispatchBroker``
  admission, a real ``ImplementWorkerRunner``, and the real
  ``runner_utils.run_lightweight_agent`` spawn seam — including the real
  per-spawn ``resolve_harness_env`` mint, the real env scrub and the real
  revoke. The only doubles are at the ports: ``FakeGitHub`` behind the real
  ``PRPort``, a store-shaped queue, a recording gateway control plane, and one
  subprocess boundary that answers ``git`` reads from a table and the CLI with a
  result envelope. **No ``AsyncMock`` of a port anywhere**;
* the brokered implement and a Classic implement reach the **same canonical
  label outcome**, because the canary adds workers beside the deterministic
  phase and takes no authority from it;
* the writer lease is really taken and really released, and a worker whose
  worktree moved while it ran is really rejected — the three things this phase
  is named after, observed through the allocator rather than asserted about a
  function.

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
from driver_phase_adapters import ImplementPhaseAdapter
from fable_director import FableDirector
from gateway_mint_client import GatewayMintCredential
from implement_broker import WriterLeaseRegistry, implement_canary_covers
from implement_worker_runner import ImplementWorkerRunner
from models import Task, WorkerResult
from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario

CANARY_REPO = "acme/widgets"
ISSUE_CLASSIC = 8831
ISSUE_BROKERED = 8832
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

ROUTE_REVISION = "route-scenario-implement"
BRANCH = "agent/issue-8832"
BASE_SHA = "4" * 40
HEAD_SHA = "5" * 40
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


class PortBackedImplementer:
    """The deterministic implement phase: it swaps the label, as the real one does."""

    def __init__(self, github: object) -> None:
        self._github = github
        self.implemented: list[int] = []

    async def run_batch(
        self, issues: list[Task] | None = None
    ) -> tuple[list[WorkerResult], list[Task]]:
        results = []
        for issue in issues or []:
            self.implemented.append(issue.id)
            await self._github.swap_pipeline_labels(issue.id, REVIEW_LABEL)
            results.append(
                WorkerResult(
                    issue_number=issue.id,
                    branch=f"agent/issue-{issue.id}",
                    success=True,
                    commits=1,
                )
            )
        return results, []


class SingleIssueStore:
    """A store that offers one implementable issue, then nothing."""

    def __init__(self, task: Task) -> None:
        self._pending = [task]
        self.released: list[int] = []
        self.requeued: list[tuple[int, str]] = []

    def get_plannable(self, max_count: int) -> list[Task]:
        return []

    def get_implementable(self, max_count: int) -> list[Task]:
        taken, self._pending = self._pending[:max_count], self._pending[max_count:]
        return taken

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


class WorktreeAndEnvelopeRunner:
    """The one process boundary this scenario has, answering both kinds of call.

    Not a mock of a port: it *is* the subprocess boundary. A ``git`` argv is
    answered from a mutable table — which is how the "the worktree moved while
    the worker ran" case is staged without reaching inside the actuator — and a
    CLI argv gets exactly the JSON envelope ``_unwrap_result_envelope`` parses,
    so the real seam's unwrapping, usage extraction and credit scan all run.
    """

    def __init__(self) -> None:
        self.git_reads: list[list[str]] = []
        self.spawns: list[dict[str, Any]] = []
        self.answers = {
            "status": f"# branch.oid {HEAD_SHA}\n# branch.head {BRANCH}\n",
            "merge-base": f"{BASE_SHA}\n",
            "diff": "--- a/upload/session.py\n+++ b/upload/session.py\n",
        }
        self.on_spawn: Any = None

    async def run_simple(self, cmd, *, env=None, input=None, timeout=None, cwd=None):  # noqa: A002
        from execution import SimpleResult

        argv = list(cmd)
        if argv[0] == "git":
            self.git_reads.append(argv)
            return SimpleResult(stdout=self.answers.get(argv[3], ""), returncode=0)
        self.spawns.append({"cmd": argv, "env": dict(env or {})})
        if self.on_spawn is not None:
            self.on_spawn()
        envelope = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "## Where\n\n`upload/session.py`, the timeout arm",
            "session_id": "sess-implement-1",
            "usage": {"input_tokens": 2400, "output_tokens": 420},
        }
        return SimpleResult(stdout=json.dumps(envelope), returncode=0)


class ScriptedTurnRunner:
    """One scripted director turn asking for a Sonnet implementer and an explorer."""

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
        lease = json.loads(payload)["lease"]
        command = {
            "kind": "dispatch_workers",
            "rationale": "read the retry arm, then propose the correction",
            "dispatches": [
                _dispatch(lease, "explorer", "claude-sonnet", 1),
                _dispatch(lease, "implementer", "claude-sonnet", 2),
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
                    "total_cost_usd": 0.03,
                },
            ],
            exit_code=0,
            usd_cost=0.03,
            latency_ms=1200,
        )


def _dispatch(lease: dict[str, Any], role: str, family: str, n: int) -> dict[str, Any]:
    return {
        "request_id": f"req-{n}",
        "driver_id": lease["driver_id"],
        "epoch": lease["epoch"],
        "phase_attempt": lease["phase_attempt"],
        "worker_role": role,
        "model_requirement": {"kind": "literal_family", "value": family},
        "task_contract": f"do the {role}'s part of the correction",
        "reason": "the retry counter double-increments",
        "expected_route_policy_revision": ROUTE_REVISION,
        "idempotency_key": f"key-{n}",
    }


def _settings(tmp_path, *, canary: str):
    from config import HydraFlowConfig
    from scheduling_model import ExecutionRuntime, SchedulingModel

    built = HydraFlowConfig(
        state_file=tmp_path / "state.json",
        repo=CANARY_REPO,
        workspace_base=tmp_path / "worktrees",
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        fable_implement_canary_repo=canary,
        gateway_base_url="http://gateway.test:8080",
    )
    for issue in (ISSUE_CLASSIC, ISSUE_BROKERED):
        built.workspace_path_for_issue(issue).mkdir(parents=True, exist_ok=True)
    return built


def _build(mock_world, tmp_path, *, name: str, issue: int, canary: str | None):
    """One allocator over the real ports, with or without an armed canary."""
    github = mock_world.github
    implementer = PortBackedImplementer(github)
    store = SingleIssueStore(Task(id=issue, title="driven issue", tags=[READY_LABEL]))
    director = None
    shadow_log = None
    leases = WriterLeaseRegistry()
    control = RecordingGatewayControlPlane()
    boundary = WorktreeAndEnvelopeRunner()
    actuator = None
    if canary is not None:
        settings = _settings(tmp_path, canary=canary)
        shadow_log = ShadowObservationLog(tmp_path / f"{name}-shadow.jsonl")
        actuator = ImplementWorkerRunner(
            config=settings,
            route_policy_revision=ROUTE_REVISION,
            runner=boundary,  # type: ignore[arg-type]
            leases=leases,
            base_ref="origin/staging",
            gateway_client=control,  # type: ignore[arg-type]
        )
        director = FableDirector(
            runner=ScriptedTurnRunner(),  # type: ignore[arg-type]
            broker=ShadowDispatchBroker(),
            shadow_log=shadow_log,
            evidence=EVIDENCE,
            repo_slug=CANARY_REPO,
            route_policy_revision=ROUTE_REVISION,
            stage_labels=STAGE_LABELS,
            usd_budget_per_boundary=5.0,
            implement_dispatcher=actuator,
            implement_is_covered=lambda phase: implement_canary_covers(
                settings, phase=phase
            ),
        )
    manager = DriverManager(
        store=store,
        labels=PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS),
        journal=DriverJournal(tmp_path / f"{name}-driver_journal.jsonl"),
        ownership=DriverOwnershipRegistry(enabled=True),
        adapters={
            DriverPhase.IMPLEMENT: ImplementPhaseAdapter(
                implementer, review_label=REVIEW_LABEL
            )
        },
        stage_labels=STAGE_LABELS,
        repo_slug=CANARY_REPO,
        max_in_flight=1,
        stage_caps={DriverPhase.IMPLEMENT: 1},
        observer=director,
    )
    return {
        "manager": manager,
        "github": github,
        "implementer": implementer,
        "shadow_log": shadow_log,
        "control": control,
        "boundary": boundary,
        "leases": leases,
        "actuator": actuator,
    }


async def _run(mock_world, tmp_path, *, name, issue, canary):
    built = _build(mock_world, tmp_path, name=name, issue=issue, canary=canary)
    await built["manager"].tick()
    built["outcome"] = {
        "labels": sorted(await built["github"].get_issue_labels(issue)),
        "implemented": [n - issue for n in built["implementer"].implemented],
    }
    return built


def _dispatched(shadow_log: ShadowObservationLog) -> list[dict[str, Any]]:
    return list(shadow_log.recent()[-1].dispatched)


@pytest.fixture
def seeded_issues(mock_world, monkeypatch):
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    for issue in (ISSUE_CLASSIC, ISSUE_BROKERED):
        IssueBuilder().numbered(issue).titled("driven issue").labeled(READY_LABEL).at(
            mock_world
        )
    return mock_world


# --------------------------------------------------------------------------
# The canary adds workers, not authority
# --------------------------------------------------------------------------


class TestABrokeredImplementReachesTheClassicOutcome:
    async def test_the_label_outcome_is_identical(
        self, seeded_issues, tmp_path
    ) -> None:
        classic = await _run(
            seeded_issues, tmp_path, name="classic", issue=ISSUE_CLASSIC, canary=None
        )
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="brokered",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )

        assert brokered["outcome"] == classic["outcome"]

    async def test_the_deterministic_phase_still_runs(
        self, seeded_issues, tmp_path
    ) -> None:
        # The whole scope line: the brokered children produce artifacts and
        # receipts *beside* the phase that owns the commit, never instead of it.
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="still-runs",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )

        assert brokered["implementer"].implemented == [ISSUE_BROKERED]

    async def test_an_actuator_armed_elsewhere_starts_nothing_here(
        self, seeded_issues, tmp_path
    ) -> None:
        """The bound refusing, with the actuator fully wired behind it.

        The first draft asserted this against the ``canary=None`` arm, where
        ``_build`` never constructs an actuator at all — so the empty lists were
        guaranteed by the test harness's own branching rather than by
        ``implement_canary_covers``. Arming for *another* repository builds the
        real actuator, wires the real subprocess boundary into it, and leaves
        only the bound to stop it.
        """
        elsewhere = await _run(
            seeded_issues,
            tmp_path,
            name="elsewhere",
            issue=ISSUE_BROKERED,
            canary="acme/other",
        )

        assert (elsewhere["boundary"].spawns, elsewhere["boundary"].git_reads) == (
            [],
            [],
        )

    async def test_an_actuator_armed_elsewhere_still_reaches_the_same_outcome(
        self, seeded_issues, tmp_path
    ) -> None:
        classic = await _run(
            seeded_issues, tmp_path, name="classic-2", issue=ISSUE_CLASSIC, canary=None
        )
        elsewhere = await _run(
            seeded_issues,
            tmp_path,
            name="elsewhere-2",
            issue=ISSUE_BROKERED,
            canary="acme/other",
        )

        assert elsewhere["outcome"] == classic["outcome"]


# --------------------------------------------------------------------------
# Each child is its own process, with its own key
# --------------------------------------------------------------------------


class TestEveryChildIsDistinctAndItsKeyIsRevoked:
    @pytest.fixture
    async def brokered(self, seeded_issues, tmp_path):
        return await _run(
            seeded_issues,
            tmp_path,
            name="children",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )

    async def test_two_admitted_requests_become_two_children(self, brokered) -> None:
        assert len(brokered["boundary"].spawns) == 2

    async def test_each_child_mints_its_own_key(self, brokered) -> None:
        assert len(brokered["control"].minted) == 2

    async def test_every_minted_key_is_revoked(self, brokered) -> None:
        # The half of "its own short-lived key" a unit test with an injected
        # spawn cannot see: the real ``resolve_harness_env`` mint and the real
        # revoke in its ``finally``.
        assert sorted(brokered["control"].revoked) == ["key-1", "key-2"]

    async def test_no_child_receives_the_gateway_control_token(self, brokered) -> None:
        # The control token mints keys; a worker holding one could mint its own.
        leaked = [
            spawn
            for spawn in brokered["boundary"].spawns
            if "control-secret" in json.dumps(spawn["env"])
        ]

        assert leaked == []

    async def test_each_child_carries_a_distinct_virtual_token(self, brokered) -> None:
        tokens = {
            spawn["env"].get("ANTHROPIC_AUTH_TOKEN")
            for spawn in brokered["boundary"].spawns
        }

        assert len(tokens) == 2

    async def test_every_accepted_receipt_carries_a_distinct_spawn(
        self, brokered
    ) -> None:
        spawn_ids = {
            row["child_spawn_id"] for row in _dispatched(brokered["shadow_log"])
        }

        assert len(spawn_ids) == 2

    async def test_every_accepted_receipt_names_a_served_model(self, brokered) -> None:
        assert [row["served_model"] for row in _dispatched(brokered["shadow_log"])] == [
            "claude-sonnet-4-6",
            "claude-sonnet-4-6",
        ]


# --------------------------------------------------------------------------
# The fence, observed through the allocator
# --------------------------------------------------------------------------


class TestTheWriterLeaseIsRealAndTemporary:
    async def test_the_lease_is_free_once_the_boundary_ends(
        self, seeded_issues, tmp_path
    ) -> None:
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="lease-free",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )

        assert brokered["leases"].holder(ISSUE_BROKERED) is None

    async def test_the_writer_holds_the_lease_and_the_explorer_does_not(
        self, seeded_issues, tmp_path
    ) -> None:
        # "Read-only evidence workers may fan out; parallel writers remain
        # forbidden", observed at the moment each child is actually running.
        built = _build(
            seeded_issues,
            tmp_path,
            name="lease-held",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        seen: list[str | None] = []
        built["boundary"].on_spawn = lambda: seen.append(
            built["leases"].holder(ISSUE_BROKERED)
        )

        await built["manager"].tick()

        assert seen == [None, "req-2"]

    async def test_the_worktree_is_measured_before_and_after_each_child(
        self, seeded_issues, tmp_path
    ) -> None:
        # Three probes to mint the lease, then three per child to fence its
        # result. A fence measured only once would compare a reading against
        # itself.
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="measured",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )

        assert len(brokered["boundary"].git_reads) == 9


class TestAWorkerThatCameBackToAMovedTreeIsRejected:
    @pytest.fixture
    async def moved(self, seeded_issues, tmp_path):
        built = _build(
            seeded_issues,
            tmp_path,
            name="moved",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        boundary = built["boundary"]

        def land_a_commit() -> None:
            boundary.answers["status"] = (
                f"# branch.oid {'7' * 40}\n# branch.head {BRANCH}\n"
            )

        boundary.on_spawn = land_a_commit
        await built["manager"].tick()
        return built

    async def test_both_children_are_superseded(self, moved) -> None:
        assert [row["status"] for row in _dispatched(moved["shadow_log"])] == [
            "superseded",
            "superseded",
        ]

    async def test_the_receipt_names_the_stale_digest(self, moved) -> None:
        assert {row["reason"] for row in _dispatched(moved["shadow_log"])} == {
            "worktree_digest_stale"
        }

    async def test_no_superseded_artifact_survives(self, moved) -> None:
        assert moved["actuator"].artifacts == []

    async def test_the_deterministic_phase_is_unaffected(self, moved) -> None:
        # A rejected worker changes nothing about the pipeline: the label moved,
        # the phase ran, and the canary lost only its own evidence.
        assert moved["implementer"].implemented == [ISSUE_BROKERED]

    async def test_the_keys_of_superseded_children_are_still_revoked(
        self, moved
    ) -> None:
        # A fence that rejected a result but leaked its credential would be a
        # fence in name only.
        assert sorted(moved["control"].revoked) == ["key-1", "key-2"]
