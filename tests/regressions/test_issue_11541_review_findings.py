"""Defects the Plan canary shipped with, pinned end to end (#11541).

PR #11655 and #11657 each auto-merged before their review passes finished. Every
family below survived the unit layer for the same reason: the thing that would
have caught it lived one seam further out than the tests reached — which is why
the last class here drives the **production** seam and fails only the runner.

The count is deliberately not stated. An earlier header said "two", and by the
time three more families had been added it was enumerating less than half its
own file — the same "complete enumeration that has stopped being complete"
class this PR corrected at two other sites.

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
from types import SimpleNamespace
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
    """A controllable ``time.monotonic`` for the batch deadline.

    Rebinds the **name** in the module under test, not an attribute on the
    ``time`` module. ``plan_worker_runner`` does a plain ``import time``, so
    ``plan_worker_runner.time`` IS ``sys.modules["time"]`` — patching an
    attribute on it moves the clock for every library in the process, including
    the asyncio event loop, whose own clock is ``time.monotonic``. Both of these
    fixtures claimed to be module-local while doing exactly that, and one of
    them advances the clock by four minutes inside a running async test.
    """
    _CLOCK["offset"] = 0.0
    monkeypatch.setattr(
        plan_worker_runner,
        "time",
        SimpleNamespace(monotonic=lambda: _REAL_MONOTONIC() + _CLOCK["offset"]),
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
        "requesting_spawn_id": "spawn-director",  # fenced roles carry lineage
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
        # The seam sets this from ``run_simple``'s OUTCOME — it returned,
        # or it timed out. This double models the returned case. One that
        # filled `model` without it models a caught mint failure or a
        # runner that never started anything, which are real and
        # different things (see TestARunnerThatNeverStartsAProcess...).
        spawn_out["spawned"] = True
        spawn_out["model"] = kwargs["model"]
        spawn_out["provider"] = "gateway"
        spawn_out["usage"] = {"input_tokens": 100, "output_tokens": 20}
        if envelope.served_model:
            spawn_out["served_model"] = envelope.served_model
        return SimpleResult(stdout=envelope.result, returncode=0)


class _ControlPlane:
    """The real gateway control-plane contract, so the mint succeeds.

    The point of these tests is a runner that cannot start a process, which is
    only reachable if everything before it works.
    """

    async def mint_key(self, *, base_url, control_token, request):
        _ = (base_url, control_token, request)
        from gateway_mint_client import GatewayMintCredential

        return GatewayMintCredential(
            key_id="key-1", token="hfgw_virtual_1", expires_at="2099-08-22T12:05:00Z"
        )

    async def revoke_key(self, *, base_url, control_token, key_id):
        _ = (base_url, control_token, key_id)
        return True


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
        # The predicate the scenario cannot tell apart, told apart. Both
        # receipts are `expired` with reason `worker_timeout`; only the lineage
        # differs, which is the entire discriminator.
        assert accepted != ran
        assert {r["status"] for r in row.dispatched} == {"expired"}
        assert {r["reason"] for r in row.dispatched} == {"worker_timeout"}

    async def test_a_reaped_child_is_not_counted_as_refused(
        self, tmp_path: Path
    ) -> None:
        """A child that ran and did not finish cleanly is its own bucket.

        Counting it as ``workers_refused`` put a child that consumed a worker
        slot, a key and real spend in the same bucket as one that was never
        started — the same conflation the tree's ``dispatched`` flag had.
        """

        class TimedOutChild(EnvelopeSpawn):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                await super().__call__(**kwargs)
                kwargs["spawn_out"]["timed_out"] = True
                return SimpleResult(stderr="timed out after 240s", returncode=-1)

        director = _director(tmp_path, TimedOutChild(REAL_MODEL_USAGE))
        await _observe(director, 7)

        summary = director.shadow_log.summary()
        assert summary["workers_expired"] == 1
        assert summary["workers_refused"] == 0
        assert summary["workers_dispatched"] == 1


class TestARunnerThatNeverStartsAProcessIsNotAnAcceptedWorker:
    """The real seam, with a runner that fails to start anything (#11541).

    Every double in this feature stands in for ``run_lightweight_agent`` and
    therefore *cannot* reach the code that decides whether a process started.
    Nothing modelled ``run_simple`` itself failing — which is why two successive
    fixes for "an ACCEPTED receipt for a child that never ran" each closed one
    door and left the next one open: first the mint (caught inside the seam,
    fills ``model``), then the runner (raises out of ``run_simple``, and the
    flag was set on the line before it).

    So this drives the production seam — real ``run_lightweight_agent``, real
    ``resolve_harness_env``, real mint — and fails only the runner. Both cases
    are verbatim from production: ``DockerRunner._ensure_client`` re-checks the
    daemon on **every** call, and ``HostRunner`` raises ``FileNotFoundError``
    when the CLI binary is absent.
    """

    class _RunnerThatCannotStart:
        """A ``SubprocessRunner`` whose ``run_simple`` never starts anything."""

        def __init__(self, error: BaseException) -> None:
            self._error = error
            self.calls = 0

        async def run_simple(self, *args: object, **kwargs: object):
            self.calls += 1
            raise self._error

    async def _receipt(self, tmp_path: Path, monkeypatch, error: BaseException):
        monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
        config = _config(tmp_path)
        object.__setattr__(config, "gateway_base_url", "http://gateway.test:8080")
        runner = self._RunnerThatCannotStart(error)
        director = FableDirector(
            runner=SameRequestIdTurn(),  # type: ignore[arg-type]
            broker=ShadowDispatchBroker(),
            shadow_log=ShadowObservationLog(tmp_path / "shadow.jsonl"),
            evidence=EVIDENCE,
            repo_slug=CANARY_REPO,
            route_policy_revision=ROUTE_REVISION,
            stage_labels=STAGE_LABELS,
            usd_budget_per_boundary=5.0,
            # No ``spawn=``: the REAL seam runs, and only the runner fails.
            dispatcher=PlanWorkerRunner(
                config=config,
                route_policy_revision=ROUTE_REVISION,
                runner=runner,  # type: ignore[arg-type]
                gateway_client=_ControlPlane(),  # type: ignore[arg-type]
            ),
            is_covered=lambda phase: plan_canary_covers(config, phase=phase),
            latch=PlanCanaryLatch(ttl_seconds=900),
        )
        await _observe(director, 7)
        assert runner.calls == 1, "the seam never reached the runner"
        self._director = director
        return director.shadow_log.recent()[0]

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(
                RuntimeError("Docker daemon not available after 6 retries"),
                id="docker-down",
            ),
            pytest.param(
                FileNotFoundError("No such file or directory: 'claude'"),
                id="cli-missing",
            ),
        ],
    )
    async def test_it_is_never_recorded_as_accepted(
        self, tmp_path: Path, monkeypatch, error: BaseException
    ) -> None:
        row = await self._receipt(tmp_path, monkeypatch, error)

        receipt = row.dispatched[0]
        assert receipt["status"] == "rejected"
        assert receipt["reason"] == "route_unavailable"
        assert receipt["served_model"] is None
        assert receipt["child_spawn_id"] is None
        assert [node["dispatched"] for node in row.would_dispatch] == [False]

    async def test_the_rollup_counts_no_worker(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The rollup, asserted — its name promised it and its body did not.

        An earlier version re-asserted ``child_spawn_id is None``, duplicating
        the sibling test above and leaving every counter this test is named for
        unchecked. A test that does not test what it says is worse than no
        test, because the gap reads as covered.
        """
        row = await self._receipt(
            tmp_path, monkeypatch, RuntimeError("Docker daemon not available")
        )
        summary = self._director.shadow_log.summary()

        assert row.dispatched[0]["child_spawn_id"] is None
        # workers_dispatched keys on child_spawn_id, so a runner that started
        # nothing must not appear in it — nor flip shadow_mode, which reads it.
        assert summary["workers_dispatched"] == 0
        assert summary["shadow_mode"] is True
        assert summary["workers_refused"] == 1
        assert summary["workers_accepted"] == 0
        assert summary["workers_expired"] == 0
        assert summary["workers_rejected_after_spawn"] == 0

    async def test_a_substituted_model_is_not_counted_as_a_timeout(
        self, tmp_path: Path
    ) -> None:
        """The one signal this canary exists to produce, in its own bucket.

        A route that answered ``claude-opus`` with a GLM id yields a receipt
        that is ``REJECTED`` **and** carries a lineage — the child ran. An
        earlier bucketing keyed on "ran and not accepted" and filed it under
        ``workers_expired``, so the operator status reported the substitution
        as a worker reaped at its deadline. ADR-0053: ``EXPIRED`` is a
        ``ReceiptStatus`` term, and a counter named for it may only count it.
        """

        class ServedSomethingElse(EnvelopeSpawn):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                result = await super().__call__(**kwargs)
                kwargs["spawn_out"]["served_model"] = "glm-5.3"
                return result

        director = _director(tmp_path, ServedSomethingElse(REAL_MODEL_USAGE))
        await _observe(director, 7)

        row = director.shadow_log.recent()[0]
        summary = director.shadow_log.summary()

        assert row.dispatched[0]["status"] == "rejected"
        assert row.dispatched[0]["reason"] == "model_requirement_unsatisfiable"
        assert row.dispatched[0]["served_model"] is None
        # It ran: it had a key, a process and real spend.
        assert row.dispatched[0]["child_spawn_id"]
        assert summary["workers_dispatched"] == 1
        assert summary["workers_rejected_after_spawn"] == 1
        assert summary["workers_expired"] == 0
        assert summary["workers_refused"] == 0

    async def test_a_runner_that_times_out_still_names_its_child(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The other half of the outcome rule, against the production seam.

        Only a process that started can outlive a deadline, so a
        ``TimeoutError`` out of ``run_simple`` is the one exception that still
        means a child ran. Mutation-checked: dropping the flag from that arm has
        to fail something, and no double-based test can catch it — the doubles
        stand in for the seam and never reach the code that sets it.
        """
        row = await self._receipt(tmp_path, monkeypatch, TimeoutError())

        receipt = row.dispatched[0]
        assert receipt["status"] == "expired"
        assert receipt["reason"] == "worker_timeout"
        # It ran: it had a key, a process, and it was reaped.
        assert receipt["child_spawn_id"]
        assert [node["dispatched"] for node in row.would_dispatch] == [True]
