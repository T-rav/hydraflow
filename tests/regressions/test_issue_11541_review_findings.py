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
import time
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
import plan_worker_runner
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


_CLOCK = {"offset": 0.0}
_REAL_MONOTONIC = time.monotonic


@pytest.fixture(autouse=True)
def _fake_batch_clock(monkeypatch: pytest.MonkeyPatch):
    """A controllable ``time.monotonic`` for the batch deadline, patched on the
    module under test so nothing else in the process sees a moved clock."""
    _CLOCK["offset"] = 0.0
    monkeypatch.setattr(
        plan_worker_runner.time,
        "monotonic",
        lambda: _REAL_MONOTONIC() + _CLOCK["offset"],
    )


class TwoDispatchTurn:
    """A director asking for two children in one turn."""

    def __init__(self) -> None:
        self.cli_version = "2.1.239"

    async def preflight(self) -> str:
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        payload = prompt.split(CAPSULE_OPEN, 1)[1].split(CAPSULE_CLOSE, 1)[0]
        lease = json.loads(payload)["lease"]
        command = {
            "kind": "dispatch_workers",
            "rationale": "map, then judge",
            "dispatches": [
                _one(lease, "planner", "claude-sonnet", 1),
                _one(lease, "architect", "claude-opus", 2),
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


def _one(lease: dict[str, Any], role: str, family: str, n: int) -> dict[str, Any]:
    return {
        "request_id": f"req-{n}",
        "driver_id": lease["driver_id"],
        "epoch": lease["epoch"],
        "phase_attempt": lease["phase_attempt"],
        "worker_role": role,
        "model_requirement": {"kind": "literal_family", "value": family},
        "task_contract": f"the {role}'s part",
        "reason": "the plan needs it",
        "expected_route_policy_revision": ROUTE_REVISION,
        "idempotency_key": f"key-{lease['issue_number']}-{n}",
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

    It does not **choose** the served model. It builds the CLI's own result
    envelope and runs it through the production ``parse_result_envelope``, so
    the id that reaches the receipt is the one the parser extracted; the double
    only copies it across the two lines the real seam copies it across.
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


def _two_dispatch_director(tmp_path, spawn: object) -> FableDirector:
    director = _director(tmp_path, spawn)
    director._runner = TwoDispatchTurn()  # type: ignore[assignment]  # noqa: SLF001
    return director


async def _observe_two(director: FableDirector, issue: int) -> None:
    director._runner = TwoDispatchTurn()  # type: ignore[assignment]  # noqa: SLF001
    await _observe(director, issue)


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


class TestAnAdmittedRequestThatNeverRanIsNotMarkedDispatched:
    """The broker admitting is not the child running, and the tree must say so.

    This is the case that makes the ``ACCEPTED``-only filter load-bearing: the
    canary-slot refusal happens **after** the broker admitted the request, so
    the row carries a ``would_dispatch`` node *and* a receipt — and the receipt
    is ``rejected``. A tree that marked the node dispatched because a receipt
    exists would report a worker that never ran, in the record ADR-0137 B5's
    bar is read from. Mutation-checked: relaxing the filter to "any receipt"
    survives every other test in this branch and dies here.
    """

    async def test_the_refused_issue_s_node_reads_not_dispatched(
        self, tmp_path: Path, spawn: EnvelopeSpawn
    ) -> None:
        director = _director(tmp_path, spawn)
        await _observe(director, 7)

        await _observe(director, 9)

        row = director.shadow_log.recent()[-1]
        assert [node["dispatched"] for node in row.would_dispatch] == [False]
        assert [receipt["status"] for receipt in row.dispatched] == ["rejected"]

    async def test_the_issue_that_ran_still_reads_dispatched(
        self, tmp_path: Path, spawn: EnvelopeSpawn
    ) -> None:
        # Non-vacuity: the False above must be the filter's answer, not the
        # field being stuck at its default again.
        director = _director(tmp_path, spawn)

        await _observe(director, 7)

        row = director.shadow_log.recent()[0]
        assert [node["dispatched"] for node in row.would_dispatch] == [True]


class TestAChildThatRanIsDispatchedEvenWhenItsReceiptIsNotAccepted:
    """The pass-7 defect in the other direction, found by pass 8.

    A child that ran to its deadline and was reaped produces an ``EXPIRED``
    receipt — it had a spawn id and it was billed, so it *was* dispatched.
    Keying the worker tree on ``ACCEPTED`` marked its node ``dispatched:
    false``, which is the same tree-vs-receipts contradiction the hardcoded
    ``false`` was, understating instead of overstating.

    Lineage is the discriminator: a child that ran carries one, a request that
    was never started does not — which is also what makes ``WORKER_TIMEOUT``'s
    two emitters tellable apart at all.
    """

    async def _timed_out(self, tmp_path: Path):
        class TimedOutChild(EnvelopeSpawn):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                await super().__call__(**kwargs)
                kwargs["spawn_out"]["timed_out"] = True
                return SimpleResult(stderr="timed out after 240s", returncode=-1)

        director = _director(tmp_path, TimedOutChild(REAL_MODEL_USAGE))
        await _observe(director, 7)
        return director.shadow_log.recent()[0]

    async def test_the_receipt_is_expired(self, tmp_path: Path) -> None:
        row = await self._timed_out(tmp_path)

        assert [r["status"] for r in row.dispatched] == ["expired"]

    async def test_the_reaped_child_still_carries_its_spawn_id(
        self, tmp_path: Path
    ) -> None:
        # Without this the receipt is byte-identical to a request the batch
        # budget refused before starting, and the two are different facts.
        row = await self._timed_out(tmp_path)

        assert row.dispatched[0]["child_spawn_id"]

    async def test_the_tree_says_the_child_was_dispatched(self, tmp_path: Path) -> None:
        row = await self._timed_out(tmp_path)

        assert [node["dispatched"] for node in row.would_dispatch] == [True]

    async def test_a_request_that_never_started_carries_no_spawn_id(
        self, tmp_path: Path, spawn: EnvelopeSpawn
    ) -> None:
        # The other side of the discriminator: the canary-slot refusal never
        # reached a spawn, so it has no lineage and its node stays False.
        director = _director(tmp_path, spawn)
        await _observe(director, 7)

        await _observe(director, 9)

        row = director.shadow_log.recent()[-1]
        assert row.dispatched[0]["child_spawn_id"] is None
        assert [node["dispatched"] for node in row.would_dispatch] == [False]

    async def test_the_rollup_counts_only_children_that_ran(
        self, tmp_path: Path, spawn: EnvelopeSpawn
    ) -> None:
        # workers_dispatched counted every receipt, so a refusal that started
        # nothing inflated it — and could flip shadow_mode to False on a
        # boundary that spawned nothing at all.
        director = _director(tmp_path, spawn)
        await _observe(director, 7)
        await _observe(director, 9)

        summary = director.shadow_log.summary()
        assert (summary["workers_dispatched"], summary["workers_refused"]) == (1, 1)

    async def test_the_tree_and_the_receipts_agree_on_a_mixed_boundary(
        self, tmp_path: Path
    ) -> None:
        """The agreement invariant, on a boundary where the two predicates differ.

        The canary scenario asserts this too, but it cannot *fail* on it: both
        of its receipts are accepted, so keying the receipt set on ``accepted``
        or on ``child_spawn_id`` gives the same answer there. Mutation-checked
        — flipping the scenario's predicate survives; flipping it here dies.

        Here the boundary has one child that ran to its deadline and was reaped
        (``expired``, with a spawn id) and one request the batch budget refused
        before starting (``expired``, without one). Same status, opposite
        answers, which is the whole point of the discriminator.
        """
        budget = 240.0

        class OneRanOneNeverStarted(EnvelopeSpawn):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                await super().__call__(**kwargs)
                _CLOCK["offset"] += budget + 1.0
                kwargs["spawn_out"]["timed_out"] = True
                return SimpleResult(stderr="timed out", returncode=-1)

        director = _director(tmp_path, OneRanOneNeverStarted(REAL_MODEL_USAGE))
        await _observe_two(director, 7)

        row = director.shadow_log.recent()[0]
        dispatched = {
            node["request_id"] for node in row.would_dispatch if node["dispatched"]
        }
        ran = {r["request_id"] for r in row.dispatched if r["child_spawn_id"]}
        accepted = {
            r["request_id"] for r in row.dispatched if r["status"] == "accepted"
        }

        assert dispatched == ran
        assert len(ran) == 1
        # The predicate the scenario cannot tell apart, told apart.
        assert accepted != ran
