"""Two defects the Plan canary shipped with, pinned end to end (#11541).

PR #11655 auto-merged before its review passes finished. Both defects below
survived the unit layer for the same reason: the thing that would have caught
each of them lived one seam further out than the tests reached.

* **A refused batch borrowed the previous batch's decision join.** `dispatch()`
  reset `last_decision_ids` and `refuse()` did not, so the canary's one-issue
  refusal inherited whatever ids the last dispatched batch left behind —
  whenever a request id repeated across issues, which it does, because a
  director names its requests per turn and not per issue. Pinned here through
  the *director*, because the borrowing only happens across two boundaries and
  a single-runner unit test can never see it.

* **The model recorded as "served" was a billing key, not a model id.** The
  CLI's `modelUsage` is keyed on `claude-opus-4-8[1m]`, whose real id sits one
  level down as `canonicalModel`. The key satisfies a literal-family check, so
  it passed every guard and would have put a context-window suffix into the
  receipt and into every downstream join keyed on a model id. Pinned here
  through the **real** `parse_result_envelope` into a real `WorkerReceipt`,
  because every unit test writes `spawn_out["served_model"]` from a double and
  therefore bypasses the parser entirely.
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
from stream_parser import parse_result_envelope

if TYPE_CHECKING:
    from pathlib import Path

CANARY_REPO = "acme/widgets"
PLAN_LABEL = "hydraflow-plan"
ROUTE_REVISION = "route-v1"
STAGE_LABELS = {"PLAN": PLAN_LABEL, "READY": "hydraflow-ready"}
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

#: The shape the repo's own recorded CLI stream carries. The key is a BILLING
#: key; the model id is one level down.
REAL_MODEL_USAGE = {
    "claude-sonnet-4-6[1m]": {
        "inputTokens": 2,
        "outputTokens": 45,
        "canonicalModel": "claude-sonnet-4-6",
        "provider": "firstParty",
    }
}


class SameRequestIdTurn:
    """A director that names its request the same way on every turn.

    Deliberately: that is what the real one does — a request id is minted per
    turn, from the turn's own numbering, and nothing makes it unique across
    issues. The borrowed-join defect is invisible unless the ids collide.
    """

    def __init__(self) -> None:
        self.cli_version = "2.1.239"

    async def preflight(self) -> str:
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        payload = prompt.split(CAPSULE_OPEN, 1)[1].split(CAPSULE_CLOSE, 1)[0]
        lease = json.loads(payload)["lease"]
        command = {
            "kind": "dispatch_workers",
            "rationale": "draft the plan",
            "dispatches": [
                {
                    "request_id": "req-1",
                    "driver_id": lease["driver_id"],
                    "epoch": lease["epoch"],
                    "phase_attempt": lease["phase_attempt"],
                    "worker_role": "planner",
                    "model_requirement": {
                        "kind": "literal_family",
                        "value": "claude-sonnet",
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
                {"type": "result", "is_error": False, "total_cost_usd": 0.0},
            ],
            exit_code=0,
        )


class EnvelopeSpawn:
    """A spawn that answers the way the real seam does — through the parser.

    It does **not** write ``spawn_out["served_model"]`` itself. It builds the
    CLI's own result envelope and runs it through the production
    ``parse_result_envelope``, so the id that reaches the receipt is the one the
    parser extracts and not one the double chose.
    """

    def __init__(self, usage: dict[str, Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._usage = usage

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls.append(kwargs)
        envelope = parse_result_envelope(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "## Modules\n\nthe map",
                    "session_id": "sess-1",
                    "modelUsage": self._usage,
                }
            )
        )
        assert envelope is not None
        spawn_out = kwargs["spawn_out"]
        spawn_out["model"] = kwargs["model"]
        spawn_out["provider"] = "gateway"
        spawn_out["usage"] = {"input_tokens": 100, "output_tokens": 20}
        if envelope.served_model:
            spawn_out["served_model"] = envelope.served_model
        return SimpleResult(stdout=envelope.result, returncode=0)


class NeverSpawns:
    async def run_simple(self, *args: object, **kwargs: object) -> SimpleResult:
        raise AssertionError("the real spawn seam ran in a regression test")


def _config(tmp_path: Path):
    from config import HydraFlowConfig

    return HydraFlowConfig(
        state_file=tmp_path / "state.json",
        repo=CANARY_REPO,
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        fable_plan_canary_repo=CANARY_REPO,
    )


def _director(tmp_path: Path, spawn: object) -> FableDirector:
    config = _config(tmp_path)
    return FableDirector(
        runner=SameRequestIdTurn(),  # type: ignore[arg-type]
        broker=ShadowDispatchBroker(),
        shadow_log=ShadowObservationLog(tmp_path / "shadow.jsonl"),
        evidence=EVIDENCE,
        repo_slug=CANARY_REPO,
        route_policy_revision=ROUTE_REVISION,
        stage_labels=STAGE_LABELS,
        usd_budget_per_boundary=5.0,
        dispatcher=PlanWorkerRunner(
            config=config,
            route_policy_revision=ROUTE_REVISION,
            runner=NeverSpawns(),  # type: ignore[arg-type]
            spawn=spawn,  # type: ignore[arg-type]
        ),
        is_covered=lambda phase: plan_canary_covers(config, phase=phase),
        latch=PlanCanaryLatch(ttl_seconds=900),
    )


async def _observe(director: FableDirector, issue: int) -> None:
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


@pytest.fixture
def spawn() -> EnvelopeSpawn:
    return EnvelopeSpawn(REAL_MODEL_USAGE)


class TestARefusedIssueBorrowsNoDecisionJoin:
    async def test_the_refused_issue_carries_a_blank_join(
        self, tmp_path: Path, spawn: EnvelopeSpawn
    ) -> None:
        director = _director(tmp_path, spawn)
        await _observe(director, 7)

        await _observe(director, 9)

        refused = director.shadow_log.recent()[-1].dispatched
        assert [row["reason"] for row in refused] == ["canary_slot_held"]
        assert [row["route_decision_id"] for row in refused] == [""]

    async def test_the_dispatched_issue_still_carries_a_real_join(
        self, tmp_path: Path, spawn: EnvelopeSpawn
    ) -> None:
        # Non-vacuity: the assertion above must be about a blank the code chose,
        # not about a field nothing ever fills.
        director = _director(tmp_path, spawn)

        await _observe(director, 7)

        dispatched = director.shadow_log.recent()[0].dispatched
        assert dispatched[0]["route_decision_id"].startswith("plan_")


class TestTheReceiptRecordsAModelIdNotABillingKey:
    async def test_the_canonical_model_reaches_the_receipt(
        self, tmp_path: Path, spawn: EnvelopeSpawn
    ) -> None:
        director = _director(tmp_path, spawn)

        await _observe(director, 7)

        served = director.shadow_log.recent()[0].dispatched[0]["served_model"]
        assert served == "claude-sonnet-4-6"

    async def test_the_context_window_suffix_never_reaches_the_receipt(
        self, tmp_path: Path, spawn: EnvelopeSpawn
    ) -> None:
        # The suffix satisfies a literal-family check, so this is the assertion
        # that would have caught it — every guard it passes is a guard that
        # cannot.
        director = _director(tmp_path, spawn)

        await _observe(director, 7)

        served = director.shadow_log.recent()[0].dispatched[0]["served_model"]
        assert "[1m]" not in served
