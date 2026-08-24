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
from types import SimpleNamespace
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
                    # The seam sets this from ``run_simple``'s OUTCOME — it returned,
                    # or it timed out. This double models the returned case. One that
                    # filled `model` without it models a caught mint failure or a
                    # runner that never started anything, which are real and
                    # different things (see TestARunnerThatNeverStartsAProcess...).
                    "spawned": True,
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
        requesting_spawn_id="spawn-director",  # fenced roles carry lineage (#11543)
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
    """The z.ai lock that matters is a routing policy, not a legacy dial.

    An earlier draft of this class pinned ``repo_provider="zai"`` refusing every
    brokered worker. That was wrong: ``apply_repo_provider`` runs at the two
    agentic seams and never at the one-shot seam a brokered child takes, so the
    dial does not govern this spawn — the child is pinned to the gateway, which
    derives the account from the model. The real lock refuses at the resolver,
    before ``resolve_harness_env`` and therefore before any credential exists,
    and it reaches the receipt through ``spawn_out["refused"]``.
    """

    async def test_a_policy_locked_lane_is_reported_as_inadmissible(
        self, config, task
    ) -> None:
        """``EnforcementRefused`` inside the seam: the prompt was never sent.

        Asserted on the **reason code**. An earlier version asserted only
        ``served_model is None``, which is true on every refusal path — it
        passed with the whole classification stubbed to the retryable code, so
        it could not tell the case it names from any other. The double writes
        both fields because the seam always does, and ``held`` is the outcome
        the default ``on_unavailable`` actually produces.

        The refusal happens **inside** the seam, so the seam IS entered — a
        later version of this test overrode ``__call__`` without recording the
        call and then asserted ``spawn.calls == []``, which could not fail and
        asserted the opposite of what happens.
        """

        class PolicyRefused(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                self.calls.append(kwargs)
                kwargs["spawn_out"]["refused"] = "literal-family-unsatisfiable"
                kwargs["spawn_out"]["refused_outcome"] = "held"
                return SimpleResult(stderr="policy rejected", returncode=-1)

        spawn = PolicyRefused()

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert len(spawn.calls) == 1
        assert (
            receipts[0].reason_code is RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )
        assert receipts[0].served_model is None

    async def test_a_catalog_that_disagrees_with_the_requirement_is_rejected(
        self, config, task, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The check this layer *can* answer: an edit putting a non-satisfying
        # id under a family is caught before the spend rather than at the
        # receipt. Mutating the table is how that guard is killable at all.
        import plan_broker

        monkeypatch.setitem(plan_broker.PLAN_TIER_CATALOG, "claude-sonnet", "glm-5.3")
        spawn = SpawnDouble()

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert spawn.calls == []
        assert (
            receipts[0].reason_code is RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )

    async def test_a_capability_request_is_checked_the_same_way(
        self, config, task, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Exempting the capability arm would reopen the substitution path one
        # requirement kind over from the one the invariant is named after.
        import plan_broker

        monkeypatch.setitem(plan_broker.PLAN_TIER_CATALOG, "claude-opus", "glm-5.3")
        spawn = SpawnDouble()

        await _dispatch(
            _runner(config, spawn),
            task,
            [
                _request(
                    role=WorkerRole.ARCHITECT,
                    kind=ModelRequirementKind.CAPABILITY,
                    value="high-reasoning",
                )
            ],
        )

        assert spawn.calls == []


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


class TestTheSeamsOwnSignalsAreRead:
    """Pass-2 fixes: the seam reports more than a reply, and the receipt has to
    read it rather than infer it from what it asked for.

    Each of these pins a defect an adversarial review found by noticing that
    the *test double* modelled behaviour the real seam does not have — a timed
    out child that raises, and a served model that differs from the requested
    one. Both are real signals now, and both come back through ``spawn_out``.
    """

    async def test_a_timed_out_child_is_expired_not_accepted(
        self, config, task
    ) -> None:
        # The seam converts its own deadline into a soft rc=-1 and fills
        # spawn_out, so without the flag a timed-out child was recorded
        # ACCEPTED with an unusable artifact.
        class TimedOut(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                await super().__call__(**kwargs)
                kwargs["spawn_out"]["timed_out"] = True
                return SimpleResult(stderr="timed out after 240s", returncode=-1)

        receipts = await _dispatch(_runner(config, TimedOut()), task, [_request()])

        assert receipts[0].status is ReceiptStatus.EXPIRED
        assert receipts[0].reason_code is RejectionReason.WORKER_TIMEOUT

    async def test_the_receipt_prefers_the_model_the_cli_reported(
        self, config, task
    ) -> None:
        class Observed(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                result = await super().__call__(**kwargs)
                kwargs["spawn_out"]["served_model"] = "claude-sonnet-4-6-20260101"
                return result

        receipts = await _dispatch(_runner(config, Observed()), task, [_request()])

        assert receipts[0].served_model == "claude-sonnet-4-6-20260101"

    async def test_an_unobserved_model_is_recorded_as_unobserved(
        self, config, task
    ) -> None:
        # Older CLIs name no model. The requested id stands in — and the
        # artifact says the id was not observed, so the weaker claim stays
        # visible instead of being laundered into an observation.
        runner = _runner(config, SpawnDouble())

        await _dispatch(runner, task, [_request()])

        assert runner.artifacts[0].model_observed is False

    async def test_an_observed_model_is_recorded_as_observed(
        self, config, task
    ) -> None:
        class Observed(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                result = await super().__call__(**kwargs)
                kwargs["spawn_out"]["served_model"] = "claude-sonnet-4-6"
                return result

        runner = _runner(config, Observed())

        await _dispatch(runner, task, [_request()])

        assert runner.artifacts[0].model_observed is True

    @pytest.mark.parametrize(
        ("refused", "outcome", "expected"),
        [
            # The ordinary provider_lock refusal. ``on_unavailable`` defaults to
            # HOLD, so this is what a z.ai-locked repository actually produces —
            # and it is the case a "a hold is always retryable" short-circuit
            # silently reversed.
            pytest.param(
                "literal-family-unsatisfiable",
                "held",
                RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE,
                id="inadmissible-held",
            ),
            pytest.param(
                "literal-family-unsatisfiable",
                "rejected",
                RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE,
                id="inadmissible-rejected",
            ),
            pytest.param(
                "no-eligible-account",
                "held",
                RejectionReason.ROUTE_UNAVAILABLE,
                id="operational-hold",
            ),
            pytest.param(
                "capability-unmapped",
                "held",
                RejectionReason.ROUTE_UNAVAILABLE,
                id="unmapped-capability",
            ),
        ],
    )
    async def test_a_policy_refusal_is_told_apart_from_a_transport_failure(
        self, config, task, refused: str, outcome: str, expected: RejectionReason
    ) -> None:
        """Both arrive as the same soft rc=-1 and want different codes.

        The reason is the classifying axis, never the outcome: ``on_unavailable``
        is a per-policy dial over what to do when a lane is unavailable, so the
        *same inadmissible request* arrives HELD or REJECTED depending on a
        setting that says nothing about the request. Both rows above pin that.

        The double writes **both** fields because the seam always does — an
        earlier version wrote only ``refused``, which is a shape production
        never produces, and that is why a guard reading the other field went
        unnoticed.
        """

        class Refused(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                self.calls.append(kwargs)
                kwargs["spawn_out"]["refused"] = refused
                kwargs["spawn_out"]["refused_outcome"] = outcome
                return SimpleResult(stderr="routing policy said no", returncode=-1)

        receipts = await _dispatch(_runner(config, Refused()), task, [_request()])

        assert receipts[0].reason_code is expected

    async def test_the_batch_decision_join_is_recorded_per_request(
        self, config, task
    ) -> None:
        # ``decision_id`` is content-addressed so a receipt can be joined back
        # to why the model was chosen. A join nothing carries is decorative.
        runner = _runner(config, SpawnDouble())

        await _dispatch(runner, task, [_request(request_id="r1")])

        assert runner.last_decision_ids["r1"] == runner.decisions[0].decision_id

    def test_the_diagnostic_accumulators_are_bounded(self, config) -> None:
        from plan_worker_runner import MAX_RETAINED_RECORDS, PlanWorkerArtifact

        runner = _runner(config, SpawnDouble())
        for n in range(MAX_RETAINED_RECORDS + 10):
            runner.artifacts.append(
                PlanWorkerArtifact(
                    request_id=str(n),
                    role="planner",
                    served_model="claude-sonnet-4-6",
                    model_observed=True,
                    decision_id="d",
                    text="x",
                )
            )

        assert len(runner.artifacts) == MAX_RETAINED_RECORDS


class TestTheRefusalClassificationIsTotal:
    """Every resolver reason is classified, and the set is derived not copied.

    The first draft of ``_INADMISSIBLE_ROUTE_REASONS`` was hand-written string
    literals: it contained a member that does not exist and omitted one that
    does, and read as a working classification while classifying nothing.
    """

    def test_every_resolver_reason_is_classified(self) -> None:
        from hydraflow_gateway.routing_policy import DecisionReason
        from plan_worker_runner import (
            _INADMISSIBLE_ROUTE_REASONS,
            _OPERATIONAL_ROUTE_REASONS,
        )

        classified = _INADMISSIBLE_ROUTE_REASONS | _OPERATIONAL_ROUTE_REASONS

        assert {reason.value for reason in DecisionReason} == classified

    def test_the_two_classes_do_not_overlap(self) -> None:
        from plan_worker_runner import (
            _INADMISSIBLE_ROUTE_REASONS,
            _OPERATIONAL_ROUTE_REASONS,
        )

        assert not (_INADMISSIBLE_ROUTE_REASONS & _OPERATIONAL_ROUTE_REASONS)

    def test_a_policy_conflict_is_inadmissible(self) -> None:
        # A retry against an unresolved conflict is an infinite one.
        from plan_worker_runner import _INADMISSIBLE_ROUTE_REASONS

        assert "policy-conflict" in _INADMISSIBLE_ROUTE_REASONS

    def test_an_unclassified_reason_falls_back_to_retryable(self) -> None:
        # Total by construction above, so this pins the default a future
        # unmapped reason would take rather than leaving it to be discovered.
        from plan_worker_runner import _refusal_for_spawn

        assert (
            _refusal_for_spawn(
                {
                    "refused": "something-nobody-wired-up",
                    "refused_outcome": "rejected",
                }
            )
            is RejectionReason.ROUTE_UNAVAILABLE
        )

    def test_a_spawn_that_left_nothing_behind_is_retryable(self) -> None:
        # The CH-6 gate's early return fills nothing at all.
        from plan_worker_runner import _refusal_for_spawn

        assert _refusal_for_spawn({}) is RejectionReason.ROUTE_UNAVAILABLE

    def test_every_broker_refusal_reason_has_a_receipt_code(self) -> None:
        """``_REFUSAL_CODES`` is indexed on the live dispatch path.

        A ``KeyError`` there is a likely-bug exception, so
        ``reraise_on_credit_or_bug`` would carry it out of the boundary
        observer — breaking ADR-0137's "a shadow component must not be able to
        fail what it observes". Its sibling table got a totality guard and this
        one did not.
        """
        from plan_broker import PlanRouteReason
        from plan_worker_runner import _REFUSAL_CODES

        assert set(_REFUSAL_CODES) == set(PlanRouteReason) - {PlanRouteReason.NONE}


class TestARefusedBatchCarriesNoBorrowedJoin:
    """`refuse()` mints blank decisions, so it must mint a blank join too.

    Found by a third review pass, and introduced by the second one's own fix:
    ``dispatch()`` reset ``last_decision_ids`` and ``refuse()`` did not, so a
    latch refusal inherited the *previous* batch's ids whenever a request id
    repeated across issues — which it does, because a director names its
    requests per turn rather than per issue. The field this canary added to make
    the join real was recording a false one.
    """

    async def test_a_refusal_after_a_dispatch_carries_no_id(self, config, task) -> None:
        runner = _runner(config, SpawnDouble())
        await _dispatch(runner, task, [_request(request_id="req-1")])
        dispatched_id = runner.last_decision_ids["req-1"]

        runner.refuse(
            [_request(request_id="req-1", key="other")],
            RejectionReason.CANARY_SLOT_HELD,
        )

        assert dispatched_id
        assert runner.last_decision_ids["req-1"] == ""

    async def test_the_outcome_does_not_override_the_reason(self, config, task) -> None:
        """A HELD ``literal-family-unsatisfiable`` is still inadmissible.

        The premise "a hold is retryable whatever its reason" is the bug: with
        ``on_unavailable`` defaulting to HOLD, the ordinary provider-lock
        refusal *is* a hold, and treating it as retryable sends an operator to
        the gateway for a problem only a policy edit fixes.
        """

        class Held(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                kwargs["spawn_out"]["refused"] = "literal-family-unsatisfiable"
                kwargs["spawn_out"]["refused_outcome"] = "held"
                return SimpleResult(stderr="held", returncode=-1)

        receipts = await _dispatch(_runner(config, Held()), task, [_request()])

        assert (
            receipts[0].reason_code is RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )


class TestOnlyAChildThatExistedCarriesASpawnId:
    """`lineage` is the discriminator `WORKER_TIMEOUT`'s contract promises, so
    exactly the paths that follow a real spawn may carry one.

    Three successive versions of this rule were wrong, each one door further
    in, and the class docstring is where they are recorded so the next reader
    does not re-derive them:

    * keyed on the ``except`` clause — but ``run_lightweight_agent`` swallows a
      failed spawn into a soft ``rc=-1``, so which clause fired says nothing;
    * keyed on ``spawn_out["model"]`` — but a ``GatewayMintError`` is caught
      *inside* the seam and its ``finally`` fills ``model`` anyway, so a
      gateway outage minted an ACCEPTED receipt for a child that never started;
    * set ``spawned`` on the line *before* ``run_simple`` — but a
      ``DockerRunner`` re-checks its daemon on every call and a ``HostRunner``
      raises when the CLI binary is missing, so the same false ACCEPTED receipt
      came back through a Docker outage instead of a gateway one.

    The rule is now ``run_simple``'s **outcome**: it returned, or it timed out.
    The cases these tests cannot reach — the ones inside the real seam — are
    covered against the production seam in
    ``tests/regressions/test_issue_11541_review_findings.py``, because a double
    standing in for the seam can never exercise the code that decides whether a
    process started.
    """

    async def test_a_gateway_outage_names_no_child(self, config, task) -> None:
        """The seam CATCHES a mint failure; it does not raise it at us.

        ``GatewayMintError`` is neither fatal nor a likely bug, so
        ``run_lightweight_agent`` converts it to a soft ``rc=-1`` — and its
        ``finally`` still fills ``model``. A double that raised the error out of
        the seam modelled something production never does, and hid that keying
        "a child ran" on ``model`` attributes a spawn id to a mint that produced
        no child. This double does what the seam does.
        """

        class MintFailed(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                self.calls.append(kwargs)
                kwargs["spawn_out"].update(
                    {"model": kwargs["model"], "provider": "gateway", "usage": {}}
                )
                return SimpleResult(stderr="gateway unreachable", returncode=-1)

        spawn = MintFailed()

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert receipts[0].lineage is None
        assert receipts[0].status is not ReceiptStatus.ACCEPTED

    async def test_a_refusal_before_the_seam_names_no_child(self, config, task) -> None:
        # The CH-6 gate / enforcement-refusal shape: the seam returns before
        # its try block, so it fills neither `spawned` nor `model`.
        class NeverSpawned(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                self.calls.append(kwargs)
                return SimpleResult(stderr="refused", returncode=-1)

        receipts = await _dispatch(_runner(config, NeverSpawned()), task, [_request()])

        assert receipts[0].lineage is None

    async def test_a_batch_budget_refusal_names_no_child(self, config, task) -> None:
        class VerySlowSpawn(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                _elapse(float(config.fable_plan_worker_timeout_seconds) + 1.0)
                return await super().__call__(**kwargs)

        receipts = await _dispatch(
            _runner(config, VerySlowSpawn()),
            task,
            [
                _request(key="k1", request_id="r1"),
                _request(key="k2", request_id="r2"),
            ],
        )

        assert receipts[1].lineage is None

    async def test_a_reaped_child_does_name_one(self, config, task) -> None:
        # Non-vacuity: the three Nones above must be the code's answer, not the
        # field being unreachable.
        class TimedOut(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                await super().__call__(**kwargs)
                kwargs["spawn_out"]["timed_out"] = True
                return SimpleResult(stderr="timed out", returncode=-1)

        receipts = await _dispatch(_runner(config, TimedOut()), task, [_request()])

        assert receipts[0].lineage is not None
        assert receipts[0].status is ReceiptStatus.EXPIRED

    async def test_a_timeout_before_the_seam_spawned_names_no_child(
        self, config, task
    ) -> None:
        """A ``TimeoutError`` escaping the seam does not imply a child.

        The seam handles its own deadline and converts it to a soft rc=-1, so
        what escapes comes from the work *around* the spawn — the CH-6 gate,
        the route-shadow and enforcement threads, or a Docker socket, where
        ``socket.timeout`` IS ``TimeoutError``. An earlier version attached a
        spawn id here on the strength of a comment asserting the opposite, and
        this PR's own double (``SpawnDouble(raises=TimeoutError())``) raises
        before it touches ``spawn_out`` — modelling exactly the case that never
        spawned.
        """
        spawn = SpawnDouble(raises=TimeoutError())

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert receipts[0].status is ReceiptStatus.EXPIRED
        assert receipts[0].reason_code is RejectionReason.WORKER_TIMEOUT
        assert receipts[0].lineage is None

    async def test_a_timeout_after_the_seam_spawned_names_its_child(
        self, config, task
    ) -> None:
        # Non-vacuity, and the other half of the rule: once the seam recorded
        # ``spawned`` a process really had started, so a deadline arriving after
        # it describes a child that ran.
        class SpawnedThenRaised(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                await super().__call__(**kwargs)
                raise TimeoutError

        receipts = await _dispatch(
            _runner(config, SpawnedThenRaised()), task, [_request()]
        )

        assert receipts[0].lineage is not None

    async def test_a_caught_mint_failure_is_never_recorded_as_accepted(
        self, config, task
    ) -> None:
        """The live defect the honest double exposed, pinned.

        A gateway outage reaches the seam's try block, so its ``finally`` fills
        ``model`` — and the guard that was meant to catch "the seam returned
        before it spawned anything" keyed on exactly that field. A mint failure
        therefore fell through to the ACCEPTED receipt: a worker recorded as
        accepted, with a spawn id, a served model and zero cost, for a child
        that never existed, in the record ADR-0137 B5's bar is read from.

        This predates the review chain — it shipped in #11655 and survived nine
        passes, because every double raised the mint error out of the seam
        instead of doing what the seam does with it.
        """

        class MintFailed(SpawnDouble):
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                self.calls.append(kwargs)
                kwargs["spawn_out"].update(
                    {"model": kwargs["model"], "provider": "gateway", "usage": {}}
                )
                return SimpleResult(stderr="gateway unreachable", returncode=-1)

        receipts = await _dispatch(_runner(config, MintFailed()), task, [_request()])

        assert receipts[0].status is ReceiptStatus.REJECTED
        assert receipts[0].reason_code is RejectionReason.ROUTE_UNAVAILABLE
        assert receipts[0].served_model is None
        assert receipts[0].lineage is None
        assert receipts[0].usd_cost == 0.0

    async def test_a_failure_around_the_spawn_names_no_child(
        self, config, task
    ) -> None:
        """The ``except Exception`` arm: work *around* the spawn, not the spawn.

        What lands here is `_terminal_gateway_runner` failing to open a Docker
        client, a non-`EnforcementRefused` failure from the route-shadow or
        enforcement threads, or a non-`PromptGateBlockedError` from the CH-6
        gate — all before a child exists. Mutation-checked: re-attaching a
        lineage on this arm has to fail something, and until this test existed
        it failed nothing.
        """
        spawn = SpawnDouble(raises=OSError("docker socket unavailable"))

        receipts = await _dispatch(_runner(config, spawn), task, [_request()])

        assert receipts[0].reason_code is RejectionReason.ROUTE_UNAVAILABLE
        assert receipts[0].lineage is None
