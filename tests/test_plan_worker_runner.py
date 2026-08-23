"""The brokered Plan canary's actuator (#11541).

:mod:`plan_broker` decides; this is the module that turns a decision into a
child process and a receipt. The claims under test are the ones the issue's
acceptance criteria are written in:

* every accepted child is **one** process with its own identity, route
  decision, receipt, budget and lineage;
* the **served** model on the receipt is the model the spawn actually ran on,
  read back off the seam rather than echoed from the request;
* a literal family is never served by a non-Anthropic model — the refusal
  happens **before** the spawn, so a refused route costs nothing;
* stop, a stale epoch, a moved label, a moved policy revision, a replayed
  idempotency key, a gateway outage and a timeout each produce **zero**
  dispatches and a receipt that says which.

The spawn seam is injected so these run without a gateway; the MockWorld
scenario drives the real one. ``test_the_default_spawn_is_the_real_seam`` keeps
that injection from being a seam in name only, which is how the s51/s56/s57
wedges happened.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import plan_worker_runner
from driver_contracts import (
    DriverLease,
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    ReceiptStatus,
    RejectionReason,
    WorkerDispatchRequest,
    WorkerRole,
)
from execution import SimpleResult
from models import Task
from plan_worker_runner import PlanWorkerRunner, build_plan_worker_prompt

ROUTE_REVISION = "route-test-1"
PLAN_LABEL = "hydraflow-plan"

_CLOCK = {"offset": 0.0}
_REAL_MONOTONIC = time.monotonic


def _elapse(seconds: float) -> None:
    """Move the batch clock forward without sleeping through the budget."""
    _CLOCK["offset"] += seconds


@pytest.fixture(autouse=True)
def _fake_batch_clock(monkeypatch: pytest.MonkeyPatch):
    """A controllable ``time.monotonic`` for the batch deadline.

    Patched on the module under test rather than globally: a global patch would
    change the clock every other library in the process reads, and the point is
    to move one budget forward, not to stop time.
    """
    _CLOCK["offset"] = 0.0
    monkeypatch.setattr(
        plan_worker_runner.time,
        "monotonic",
        lambda: _REAL_MONOTONIC() + _CLOCK["offset"],
    )


class SpawnDouble:
    """Stands in for ``run_lightweight_agent``. Records what it was asked for."""

    def __init__(
        self,
        *,
        stdout: str = "worker output",
        returncode: int = 0,
        served_model: str | None = None,
        raises: BaseException | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._stdout = stdout
        self._returncode = returncode
        self._served_model = served_model
        self._raises = raises

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        spawn_out = kwargs.get("spawn_out")
        if spawn_out is not None:
            served = (
                self._served_model
                if self._served_model is not None
                else kwargs["model"]
            )
            spawn_out.update(
                {
                    "model": served,
                    "provider": "gateway",
                    "usage": {"input_tokens": 1000, "output_tokens": 200},
                    "route_decision_id": "dec_abc",
                }
            )
        return SimpleResult(stdout=self._stdout, returncode=self._returncode)


def _lease(*, epoch: int = 0, attempt: int = 0) -> DriverLease:
    return DriverLease(
        driver_id="drv-1",
        epoch=epoch,
        repo_slug="acme-widgets",
        issue_number=101,
        phase=DriverPhase.PLAN,
        expected_stage_label=PLAN_LABEL,
        phase_attempt=attempt,
        expires_at=datetime.now(UTC) + timedelta(seconds=900),
    )


def _request(
    *,
    role: WorkerRole = WorkerRole.PLANNER,
    value: str = "claude-sonnet",
    kind: ModelRequirementKind = ModelRequirementKind.LITERAL_FAMILY,
    key: str = "key-1",
    request_id: str = "req-1",
) -> WorkerDispatchRequest:
    return WorkerDispatchRequest(
        request_id=request_id,
        driver_id="drv-1",
        epoch=0,
        phase_attempt=0,
        worker_role=role,
        model_requirement=ModelRequirement(kind=kind, value=value),
        task_contract="map the modules this issue touches",
        reason="the plan needs the module map first",
        expected_route_policy_revision=ROUTE_REVISION,
        idempotency_key=key,
    )


@pytest.fixture
def config(tmp_path):
    from config import HydraFlowConfig

    return HydraFlowConfig(
        state_file=tmp_path / "state.json",
        repo="acme/widgets",
        fable_plan_canary_repo="acme/widgets",
    )


@pytest.fixture
def task() -> Task:
    return Task(id=101, title="driven issue", tags=[PLAN_LABEL])


class _NeverSpawns:
    """A SubprocessRunner that would fail loudly if the real seam ever ran.

    The unit layer injects ``spawn``, so nothing here should reach a process.
    Handing the runner a stub that *raises* rather than one that quietly
    succeeds is what makes "the spawn seam was replaced" checkable instead of
    assumed.
    """

    async def run_simple(self, *args, **kwargs):
        raise AssertionError("the real spawn seam ran in a unit test")


_NEVER_SPAWNS = _NeverSpawns()


def _runner(config, spawn, **kwargs):
    defaults: dict[str, Any] = {
        "config": config,
        "route_policy_revision": ROUTE_REVISION,
        "runner": _NEVER_SPAWNS,
        "spawn": spawn,
    }
    defaults.update(kwargs)
    return PlanWorkerRunner(**defaults)


async def _dispatch(runner, task, requests, **kwargs):
    defaults: dict[str, Any] = {
        "task": task,
        "lease": _lease(),
        "phase": DriverPhase.PLAN,
        "fence": lambda: None,
    }
    defaults.update(kwargs)
    return await runner.dispatch(requests, **defaults)


class TestOneAcceptedRequestIsOneChildWithAFullReceipt:
    async def test_one_request_spawns_exactly_one_child(self, config, task) -> None:
        spawn = SpawnDouble()

        await _dispatch(_runner(config, spawn), task, [_request()])

        assert len(spawn.calls) == 1

    async def test_two_requests_spawn_two_distinct_children(self, config, task) -> None:
        spawn = SpawnDouble()

        await _dispatch(
            _runner(config, spawn),
            task,
            [
                _request(role=WorkerRole.PLANNER, key="k1", request_id="r1"),
                _request(
                    role=WorkerRole.ARCHITECT,
                    value="claude-opus",
                    key="k2",
                    request_id="r2",
                ),
            ],
        )

        assert len(spawn.calls) == 2

    async def test_each_child_carries_its_own_spawn_identity(
        self, config, task
    ) -> None:
        spawn = SpawnDouble()

        receipts = await _dispatch(
            _runner(config, spawn),
            task,
            [
                _request(key="k1", request_id="r1"),
                _request(
                    role=WorkerRole.ARCHITECT,
                    value="claude-opus",
                    key="k2",
                    request_id="r2",
                ),
            ],
        )

        spawn_ids = {r.lineage.child_spawn_id for r in receipts if r.lineage}
        assert len(spawn_ids) == 2

    async def test_the_receipt_carries_parent_driver_lineage(
        self, config, task
    ) -> None:
        receipts = await _dispatch(_runner(config, SpawnDouble()), task, [_request()])

        lineage = receipts[0].lineage
        assert lineage is not None
        assert (lineage.driver_id, lineage.epoch, lineage.depth) == ("drv-1", 0, 1)

    async def test_an_accepted_receipt_records_the_artifact_digest(
        self, config, task
    ) -> None:
        receipts = await _dispatch(_runner(config, SpawnDouble()), task, [_request()])

        assert receipts[0].artifact_digest

    async def test_an_accepted_receipt_records_a_cost(self, config, task) -> None:
        # Derived from the real token counts the seam reports, not from a
        # constant: a receipt whose cost is always zero is not evidence.
        receipts = await _dispatch(_runner(config, SpawnDouble()), task, [_request()])

        assert receipts[0].usd_cost > 0.0

    async def test_the_child_is_spawned_through_the_gateway(self, config, task) -> None:
        # The per-child short-lived key, the route decision and the ledger row
        # are all gateway properties. A brokered child on a direct lane could
        # satisfy none of them, so the transport is pinned rather than dialled.
        spawn = SpawnDouble()

        await _dispatch(_runner(config, spawn), task, [_request()])

        assert spawn.calls[0]["provider"] == "gateway"

    async def test_the_child_is_attributed_to_its_worker_role(
        self, config, task
    ) -> None:
        # ``source`` is the principal id the gateway's v2 mint joins a role on
        # (ADR-0138 D6), so a role name here is what makes the child's route
        # attributable at all.
        spawn = SpawnDouble()

        await _dispatch(_runner(config, spawn), task, [_request()])

        assert spawn.calls[0]["source"] == "planner"

    async def test_the_child_is_given_the_issues_labels(self, config, task) -> None:
        # tests/test_prompt_gate_completeness.py pins this for every call site;
        # asserted here too because the CH-6 gate silently under-enforces
        # without it.
        spawn = SpawnDouble()

        await _dispatch(_runner(config, spawn), task, [_request()])

        assert list(spawn.calls[0]["issue_labels"]) == [PLAN_LABEL]


class TestTheServedModelIsReadBackNotEchoed:
    async def test_a_sonnet_request_is_spawned_on_a_sonnet_model(
        self, config, task
    ) -> None:
        spawn = SpawnDouble()

        await _dispatch(_runner(config, spawn), task, [_request()])

        assert "sonnet" in spawn.calls[0]["model"]

    async def test_an_opus_request_is_spawned_on_an_opus_model(
        self, config, task
    ) -> None:
        spawn = SpawnDouble()

        await _dispatch(
            _runner(config, spawn),
            task,
            [_request(role=WorkerRole.ARCHITECT, value="claude-opus")],
        )

        assert "opus" in spawn.calls[0]["model"]

    async def test_the_receipt_reports_the_model_the_seam_actually_ran(
        self, config, task
    ) -> None:
        # The framing's risk 3: a fallback or pool path could satisfy
        # ``claude-opus`` with something else. Asserting the requested tier
        # would never see it; asserting the served id does.
        spawn = SpawnDouble(served_model="claude-opus-4-8")

        receipts = await _dispatch(
            _runner(config, spawn),
            task,
            [_request(role=WorkerRole.ARCHITECT, value="claude-opus")],
        )

        assert receipts[0].served_model == "claude-opus-4-8"

    async def test_a_literal_family_served_by_glm_is_refused_not_recorded(
        self, config, task
    ) -> None:
        # The named hazard, at the point where it would actually happen: the
        # seam came back reporting a GLM model for a literal Opus request. The
        # receipt must not be able to claim it.
        spawn = SpawnDouble(served_model="glm-5.3")

        receipts = await _dispatch(
            _runner(config, spawn),
            task,
            [_request(role=WorkerRole.ARCHITECT, value="claude-opus")],
        )

        assert receipts[0].status is not ReceiptStatus.ACCEPTED
        assert receipts[0].served_model is None

    async def test_the_route_decision_is_recorded_for_every_child(
        self, config, task
    ) -> None:
        runner = _runner(config, SpawnDouble())

        await _dispatch(runner, task, [_request()])

        assert runner.decisions[0].selected is True


class TestALiteralFamilyIsRefusedBeforeAnythingIsSpawned:
    @pytest.fixture
    def zai_config(self, tmp_path):
        from config import HydraFlowConfig

        return HydraFlowConfig(
            state_file=tmp_path / "state.json",
            repo="acme/widgets",
            fable_plan_canary_repo="acme/widgets",
            repo_provider="zai",
            repo_model="glm-5.3",
        )

    async def test_a_zai_locked_repository_spawns_nothing(
        self, zai_config, task
    ) -> None:
        spawn = SpawnDouble()

        await _dispatch(_runner(zai_config, spawn), task, [_request()])

        assert spawn.calls == []

    async def test_a_zai_locked_repository_reports_the_requirement_unsatisfiable(
        self, zai_config, task
    ) -> None:
        receipts = await _dispatch(
            _runner(zai_config, SpawnDouble()), task, [_request()]
        )

        assert (
            receipts[0].reason_code is RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )


class TestEveryFailClosedPathDispatchesNothing:
    @pytest.mark.parametrize(
        ("reason", "label"),
        [
            pytest.param(RejectionReason.STOP_FENCE, "stop", id="stop"),
            pytest.param(RejectionReason.STALE_EPOCH, "epoch", id="stale-epoch"),
            pytest.param(RejectionReason.LIVE_LABEL_CHANGED, "label", id="moved-label"),
            pytest.param(
                RejectionReason.ROUTE_POLICY_REVISION_STALE, "policy", id="stale-policy"
            ),
            pytest.param(RejectionReason.DRAINING, "drain", id="draining"),
        ],
    )
    async def test_a_fence_that_fires_between_admission_and_spawn_spawns_nothing(
        self, config, task, reason: RejectionReason, label: str
    ) -> None:
        # Risk 2: the check and the claim must be one step. The fence is
        # re-evaluated immediately before each spawn, with no await between,
        # so a stop or an epoch bump in that window cannot produce a late
        # dispatch.
        spawn = SpawnDouble()

        receipts = await _dispatch(
            _runner(config, spawn), task, [_request()], fence=lambda: reason
        )

        assert spawn.calls == []
        assert receipts[0].reason_code is reason

    async def test_a_replayed_idempotency_key_spawns_nothing_the_second_time(
        self, config, task
    ) -> None:
        spawn = SpawnDouble()
        runner = _runner(config, spawn)

        await _dispatch(runner, task, [_request(key="same")])
        await _dispatch(runner, task, [_request(key="same")])

        assert len(spawn.calls) == 1

    async def test_a_replayed_idempotency_key_reports_the_duplicate(
        self, config, task
    ) -> None:
        runner = _runner(config, SpawnDouble())

        await _dispatch(runner, task, [_request(key="same")])
        receipts = await _dispatch(runner, task, [_request(key="same")])

        assert receipts[0].reason_code is RejectionReason.DUPLICATE_IDEMPOTENCY_KEY

    async def test_a_gateway_outage_holds_the_dispatch(self, config, task) -> None:
        from gateway_mint_client import GatewayMintError

        spawn = SpawnDouble(raises=GatewayMintError("gateway unreachable"))

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert receipts[0].reason_code is RejectionReason.ROUTE_UNAVAILABLE

    async def test_a_gateway_outage_leaves_no_accepted_receipt(
        self, config, task
    ) -> None:
        from gateway_mint_client import GatewayMintError

        spawn = SpawnDouble(raises=GatewayMintError("gateway unreachable"))

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert receipts[0].status is ReceiptStatus.REJECTED

    async def test_a_timed_out_child_is_expired_rather_than_accepted(
        self, config, task
    ) -> None:
        spawn = SpawnDouble(raises=TimeoutError())

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert receipts[0].status is ReceiptStatus.EXPIRED

    async def test_a_credit_exhaustion_signal_is_never_swallowed(
        self, config, task
    ) -> None:
        # dark-factory 2.2: a burnt balance is a factory-wide signal, not a
        # worker failure, and eating it here would burn attempt budget against
        # an exhausted account.
        from subprocess_util import CreditExhaustedError

        spawn = SpawnDouble(raises=CreditExhaustedError("out of credit"))

        with pytest.raises(CreditExhaustedError):
            await _dispatch(_runner(config, spawn), task, [_request()])

    async def test_a_soft_failure_produces_a_receipt_that_says_so(
        self, config, task
    ) -> None:
        spawn = SpawnDouble(returncode=-1, stdout="")

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert receipts[0].output_contract_ok is False

    async def test_a_refused_spawn_that_never_ran_records_no_served_model(
        self, config, task
    ) -> None:
        # An enforcement refusal returns rc=-1 and fills nothing in, which is
        # how "the prompt was never sent" is distinguishable from "the child
        # ran and failed".
        class NeverRan(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                self.calls.append(kwargs)
                return SimpleResult(stderr="routing policy rejected", returncode=-1)

        receipts = await _dispatch(_runner(config, NeverRan()), task, [_request()])

        assert receipts[0].served_model is None


class TestTheSpawnSeamIsReal:
    def test_the_default_spawn_is_the_real_seam(self, config) -> None:
        # Asserting the parameter merely exists would pass against a runner
        # that accepts it and ignores it. This pins what runs when nobody
        # injects anything.
        from plan_worker_runner import _spawn_plan_worker

        runner = PlanWorkerRunner(
            config=config,
            route_policy_revision=ROUTE_REVISION,
            runner=_NEVER_SPAWNS,  # type: ignore[arg-type]
        )

        assert runner.spawn is _spawn_plan_worker

    def test_the_worker_prompt_carries_the_task_contract(self) -> None:
        prompt = build_plan_worker_prompt(
            role="planner",
            task_contract="map the modules this issue touches",
            issue_goal="make the widget faster",
            issue_number=101,
        )

        assert "map the modules this issue touches" in prompt

    def test_the_worker_prompt_never_carries_a_credential_field(self) -> None:
        prompt = build_plan_worker_prompt(
            role="planner",
            task_contract="do the thing",
            issue_goal="the goal",
            issue_number=101,
        )

        assert "ANTHROPIC_AUTH_TOKEN" not in prompt


class TestTheBatchBudgetBoundsTheAllocatorTick:
    """The dispatch is awaited inside the allocator tick, so the budget has to
    bound the whole batch — a per-child one would let a single boundary block
    every other driver for ``MAX_DISPATCH_BATCH`` times the dial.
    """

    async def test_the_first_child_is_given_the_whole_budget(
        self, config, task
    ) -> None:
        spawn = SpawnDouble()

        await _dispatch(_runner(config, spawn), task, [_request()])

        assert spawn.calls[0]["timeout"] == pytest.approx(
            config.fable_plan_worker_timeout_seconds, abs=1.0
        )

    async def test_a_later_child_is_given_only_what_is_left(self, config, task) -> None:
        class SlowSpawn(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                _elapse(120.0)
                return await super().__call__(**kwargs)

        spawn = SlowSpawn()

        await _dispatch(
            _runner(config, spawn),
            task,
            [
                _request(key="k1", request_id="r1"),
                _request(
                    role=WorkerRole.ARCHITECT,
                    value="claude-opus",
                    key="k2",
                    request_id="r2",
                ),
            ],
        )

        assert spawn.calls[1]["timeout"] < spawn.calls[0]["timeout"]

    async def test_a_batch_that_has_spent_its_budget_starts_no_more_children(
        self, config, task
    ) -> None:
        class VerySlowSpawn(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                _elapse(float(config.fable_plan_worker_timeout_seconds) + 1.0)
                return await super().__call__(**kwargs)

        spawn = VerySlowSpawn()

        receipts = await _dispatch(
            _runner(config, spawn),
            task,
            [
                _request(key="k1", request_id="r1"),
                _request(
                    role=WorkerRole.ARCHITECT,
                    value="claude-opus",
                    key="k2",
                    request_id="r2",
                ),
            ],
        )

        assert len(spawn.calls) == 1
        assert receipts[1].reason_code is RejectionReason.WORKER_TIMEOUT

    async def test_a_child_refused_for_budget_is_still_replayable(
        self, config, task
    ) -> None:
        # Its key must NOT be claimed: the work never ran, so a later boundary
        # asking for it again is a fresh request rather than a duplicate.
        class VerySlowSpawn(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                _elapse(float(config.fable_plan_worker_timeout_seconds) + 1.0)
                return await super().__call__(**kwargs)

        spawn = VerySlowSpawn()
        runner = _runner(config, spawn)
        await _dispatch(
            runner,
            task,
            [
                _request(key="k1", request_id="r1"),
                _request(key="k2", request_id="r2"),
            ],
        )
        spawn._raises = None
        receipts = await _dispatch(runner, task, [_request(key="k2", request_id="r2")])

        assert receipts[0].reason_code is not RejectionReason.DUPLICATE_IDEMPOTENCY_KEY

    def test_the_replay_fence_is_bounded(self, config) -> None:
        # An unbounded set on an object that lives for the whole run is a slow
        # leak with no upper bound at all.
        from plan_worker_runner import MAX_DISPATCHED_KEYS

        runner = _runner(config, SpawnDouble())
        for n in range(MAX_DISPATCHED_KEYS + 50):
            runner._claim(f"key-{n}")

        assert len(runner._dispatched_keys) == MAX_DISPATCHED_KEYS
