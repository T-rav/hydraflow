"""The Implement canary's actuator, driven through its real seams (#11542).

The spawn is injected and the git reads go through an injected
``SubprocessRunner``, so every test below runs the actuator's own code — the
real tier resolution, the real lease, the real fence, the real receipt
construction — against doubles at the two places it touches the world. Nothing
here is an ``AsyncMock`` of a port.

The classes follow the phase's acceptance criteria: one child per request, one
writer at a time, a fence that rejects rather than drops, a budget that bounds
the batch, and authority that ends when the worker does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from config import HydraFlowConfig
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
from implement_broker import WriterLeaseRegistry, worktree_diff_digest
from implement_worker_runner import (
    MAX_DIFF_CHARS,
    ImplementWorkerRunner,
    WorktreeMeasurement,
    build_implement_worker_prompt,
)
from models import Task
from scheduling_model import ExecutionRuntime, SchedulingModel

if TYPE_CHECKING:
    from pathlib import Path

REPO = "acme/widgets"
READY_LABEL = "hydraflow-ready"
ROUTE_REVISION = "route-v1"
BRANCH = "agent/issue-7"
BASE = "a" * 40
HEAD = "b" * 40
BASE_REF = "origin/staging"


class GitScript:
    """A ``SubprocessRunner`` answering only ``git``, from a scripted table.

    Keyed on the git subcommand so a test can move one token between two
    measurements without restating the other two. Answers are read from a
    mutable dict, which is how a test makes the worktree move *while a child
    runs* without reaching inside the runner.
    """

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.answers: dict[str, str] = answers or {
            "status": f"# branch.oid {HEAD}\n# branch.head {BRANCH}\n",
            "merge-base": f"{BASE}\n",
            "diff": "--- a\n+++ b\n",
        }
        self.failing: set[str] = set()
        self.calls: list[list[str]] = []

    async def run_simple(self, cmd: Any, **kwargs: Any) -> SimpleResult:
        argv = list(cmd)
        self.calls.append(argv)
        assert argv[0] == "git", "the actuator ran something other than a git read"
        subcommand = argv[3]
        if subcommand in self.failing:
            return SimpleResult(stderr="fatal", returncode=128)
        return SimpleResult(stdout=self.answers.get(subcommand, ""), returncode=0)


class SpawnRecorder:
    """Stands in for ``run_lightweight_agent`` and records every call.

    Optionally runs a callback between the spawn starting and its reply, which
    is how the "the worktree moved under the worker" cases are staged: the tree
    changes at exactly the moment a real child would be thinking.
    """

    def __init__(self, *, served: str | None = None, while_running: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._served = served
        self._while_running = while_running

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls.append(kwargs)
        if self._while_running is not None:
            self._while_running()
        spawn_out = kwargs.get("spawn_out")
        if spawn_out is not None:
            spawn_out.update(
                {
                    "model": self._served or kwargs["model"],
                    "provider": "gateway",
                    "usage": {"input_tokens": 400, "output_tokens": 90},
                }
            )
        return SimpleResult(stdout="## Where\n\n`upload/session.py`", returncode=0)


class ExplodingSpawn:
    """A spawn that raises the way a gateway outage does."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls += 1
        raise self.error


def _config(tmp_path: Path, **overrides: object) -> HydraFlowConfig:
    settings = HydraFlowConfig(
        state_file=tmp_path / "state.json",
        repo=REPO,
        workspace_base=tmp_path / "worktrees",
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        fable_implement_canary_repo=REPO,
        **overrides,  # type: ignore[arg-type]
    )
    settings.workspace_path_for_issue(7).mkdir(parents=True, exist_ok=True)
    return settings


def _lease(*, epoch: int = 3, attempt: int = 1) -> DriverLease:
    from datetime import UTC, datetime, timedelta

    return DriverLease(
        driver_id="drv-7",
        epoch=epoch,
        repo_slug=REPO,
        issue_number=7,
        phase=DriverPhase.IMPLEMENT,
        expected_stage_label=READY_LABEL,
        phase_attempt=attempt,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def _request(
    *,
    role: WorkerRole = WorkerRole.IMPLEMENTER,
    request_id: str = "req-1",
    key: str = "key-1",
    kind: ModelRequirementKind = ModelRequirementKind.LITERAL_FAMILY,
    value: str = "claude-sonnet",
) -> WorkerDispatchRequest:
    return WorkerDispatchRequest(
        request_id=request_id,
        driver_id="drv-7",
        epoch=3,
        phase_attempt=1,
        worker_role=role,
        model_requirement=ModelRequirement(kind=kind, value=value),
        task_contract="fix the double-counted retry",
        reason="the review found a double increment",
        expected_route_policy_revision=ROUTE_REVISION,
        idempotency_key=key,
    )


def _task() -> Task:
    return Task(id=7, title="make the widget faster", tags=[READY_LABEL])


def _measurement(**overrides: str) -> WorktreeMeasurement:
    from implement_broker import WorktreeState

    fields: dict[str, str] = {
        "branch": BRANCH,
        "base_sha": BASE,
        "head_sha": HEAD,
        "diff_digest": worktree_diff_digest("--- a\n+++ b\n"),
    }
    fields.update(overrides)
    return WorktreeMeasurement(
        state=WorktreeState(**fields),  # type: ignore[arg-type]
        diff_excerpt="--- a\n+++ b\n",
    )


def _facts(
    *,
    owner: str = "drv-7",
    epoch: int = 3,
    attempt: int = 1,
    label: str = READY_LABEL,
) -> Any:
    """The four ownership tokens the fence re-reads. The fourth is a LABEL.

    Spelled out because the first draft of the director passed the driver
    *state* here, which compared ``"READY"`` against ``"hydraflow-ready"`` and
    superseded every worker.
    """
    return lambda: (owner, epoch, attempt, label)


def _build(
    tmp_path: Path,
    *,
    spawn: Any = None,
    git: GitScript | None = None,
    leases: WriterLeaseRegistry | None = None,
    **config_overrides: object,
) -> tuple[ImplementWorkerRunner, GitScript]:
    scripted = git or GitScript()
    runner = ImplementWorkerRunner(
        config=_config(tmp_path, **config_overrides),
        route_policy_revision=ROUTE_REVISION,
        runner=scripted,  # type: ignore[arg-type]
        leases=leases or WriterLeaseRegistry(),
        base_ref=BASE_REF,
        spawn=spawn or SpawnRecorder(),
    )
    return runner, scripted


async def _dispatch(
    runner: ImplementWorkerRunner,
    requests: Any,
    *,
    measured: WorktreeMeasurement | None = None,
    fence: Any = None,
    facts: Any = None,
) -> Any:
    return await runner.dispatch(
        requests,
        task=_task(),
        lease=_lease(),
        phase=DriverPhase.IMPLEMENT,
        measured=measured or _measurement(),
        fence=fence or (lambda: None),
        driver_facts=facts or _facts(),
    )


# --------------------------------------------------------------------------
# One admitted request, one child
# --------------------------------------------------------------------------


class TestOneRequestBecomesOneChild:
    async def test_an_admitted_request_starts_exactly_one_child(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        await _dispatch(runner, [_request()])

        assert len(spawn.calls) == 1

    async def test_the_child_is_pinned_to_the_gateway(self, tmp_path: Path) -> None:
        # The key, the route decision and the ledger row are all gateway
        # properties; a brokered child on a direct lane would carry none.
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        await _dispatch(runner, [_request()])

        assert spawn.calls[0]["provider"] == "gateway"

    async def test_the_child_names_its_catalogued_role_as_the_principal(
        self, tmp_path: Path
    ) -> None:
        # Load-bearing rather than cosmetic: the governed route resolver keys on
        # ``principal_id=source``, so a loop-shaped source would mint unbound.
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        await _dispatch(runner, [_request(role=WorkerRole.DEBUGGER)])

        assert spawn.calls[0]["source"] == "debugger"

    async def test_the_child_receives_the_issue_labels(self, tmp_path: Path) -> None:
        # The CH-6 gate's upward-only data-class elevation reads these.
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        await _dispatch(runner, [_request()])

        assert spawn.calls[0]["issue_labels"] == (READY_LABEL,)

    async def test_the_accepted_receipt_carries_parent_driver_lineage(
        self, tmp_path: Path
    ) -> None:
        runner, _git = _build(tmp_path)

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].lineage is not None and receipts[0].lineage.epoch == 3

    async def test_the_accepted_receipt_records_the_served_model(
        self, tmp_path: Path
    ) -> None:
        runner, _git = _build(tmp_path)

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].served_model == "claude-sonnet-4-6"

    async def test_a_substituted_model_is_refused_rather_than_recorded(
        self, tmp_path: Path
    ) -> None:
        # The named hazard: a GLM model must never be reported as Sonnet. The
        # served id is read back off the seam, not echoed from the request.
        runner, _git = _build(tmp_path, spawn=SpawnRecorder(served="glm-5.3"))

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is (
            RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )

    async def test_a_seam_that_never_spawned_reports_no_route(
        self, tmp_path: Path
    ) -> None:
        """A CH-6 block or an enforcement refusal returns before any inference.

        ``run_lightweight_agent`` collapses both to its soft-failure contract
        and leaves ``spawn_out`` empty, so there is no served model and nothing
        to bill. That must read as ``ROUTE_UNAVAILABLE`` — a state an operator
        can fix — rather than as a model substitution, which is what the empty
        string would be classified as if the guard were gone. Mutation testing
        found nothing covered this.
        """

        class SilentSpawn:
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                # Deliberately does NOT populate ``spawn_out``.
                return SimpleResult(stderr="blocked before spawn", returncode=-1)

        runner, _git = _build(tmp_path, spawn=SilentSpawn())

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is RejectionReason.ROUTE_UNAVAILABLE

    async def test_a_seam_that_never_spawned_records_no_artifact(
        self, tmp_path: Path
    ) -> None:
        class SilentSpawn:
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                return SimpleResult(stderr="blocked before spawn", returncode=-1)

        runner, _git = _build(tmp_path, spawn=SilentSpawn())

        await _dispatch(runner, [_request()])

        assert list(runner.artifacts) == []

    async def test_a_timed_out_child_is_expired_not_accepted(
        self, tmp_path: Path
    ) -> None:
        """The seam never raises ``TimeoutError`` — it returns a soft rc=-1.

        So the ``except TimeoutError`` arm is unreachable in production, and
        without the seam's own ``timed_out`` signal a child that blew its
        deadline was recorded ACCEPTED with an unusable artifact. #11657 found
        this on the Plan actuator; the same unreachable arm had already been
        copied here.
        """

        class TimedOutSpawn:
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                spawn_out = kwargs["spawn_out"]
                spawn_out.update({"model": kwargs["model"], "timed_out": True})
                return SimpleResult(stderr="timed out after 240s", returncode=-1)

        runner, _git = _build(tmp_path, spawn=TimedOutSpawn())

        receipts = await _dispatch(runner, [_request()])

        assert (receipts[0].status, receipts[0].reason_code) == (
            ReceiptStatus.EXPIRED,
            RejectionReason.WORKER_TIMEOUT,
        )

    async def test_an_inadmissible_route_is_not_reported_as_retryable(
        self, tmp_path: Path
    ) -> None:
        """A routing policy that refuses this spawn will refuse it again.

        ``ROUTE_UNAVAILABLE``'s own contract says a caretaker retry is correct
        and an operator should look at the gateway. For an inadmissible route
        both halves are wrong: the thing to edit is a policy.
        """

        class RefusedSpawn:
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                kwargs["spawn_out"].update(
                    {
                        "refused": "literal-family-unsatisfiable",
                        "refused_outcome": "held",
                    }
                )
                return SimpleResult(stderr="refused", returncode=-1)

        runner, _git = _build(tmp_path, spawn=RefusedSpawn())

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is (
            RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )

    @pytest.mark.parametrize(
        "reason",
        [
            pytest.param("model-not-allowed", id="model-not-allowed"),
            pytest.param("policy-conflict", id="policy-conflict"),
        ],
    )
    async def test_the_other_inadmissible_reasons_are_not_retryable_either(
        self, tmp_path: Path, reason: str
    ) -> None:
        """The two a hand-written copy of this set missed.

        The first port of this classifier invented its reason strings instead of
        reading ``DecisionReason``: two of the four matched no member at all,
        and these two — the ones that matter — were absent, so both would have
        been reported as retryable. ``POLICY_CONFLICT`` especially: a retry
        against an unresolved conflict is an infinite one. The set is now shared
        with the Plan actuator and covered by its totality test, and these pin
        the classification through *this* actuator so the sharing cannot be
        quietly undone.
        """

        class RefusedSpawn:
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                kwargs["spawn_out"].update(
                    {"refused": reason, "refused_outcome": "rejected"}
                )
                return SimpleResult(stderr="refused", returncode=-1)

        runner, _git = _build(tmp_path, spawn=RefusedSpawn())

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is (
            RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )

    async def test_a_transport_failure_stays_retryable(self, tmp_path: Path) -> None:
        # The contrast, and the reason the classifier reads the REASON rather
        # than the outcome: a HELD outcome with no policy reason is a transport
        # failure, and a retry is exactly right for it.
        class UnreachableSpawn:
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                return SimpleResult(stderr="connection refused", returncode=-1)

        runner, _git = _build(tmp_path, spawn=UnreachableSpawn())

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is RejectionReason.ROUTE_UNAVAILABLE

    async def test_an_unobserved_model_is_recorded_as_unobserved(
        self, tmp_path: Path
    ) -> None:
        """A weak claim that says so beats one that looks strong.

        ``spawn_out["model"]`` is the id this runner passed in; it only becomes
        the effective model when the *gateway* enforcement canary is armed — an
        independent dial. So in the default configuration the served-model
        re-check compared the tier catalog's answer against the requirement
        that produced it and could not fail.
        """
        runner, _git = _build(tmp_path, spawn=SpawnRecorder())

        await _dispatch(runner, [_request()])

        assert runner.artifacts[0].model_observed is False

    async def test_a_model_the_cli_reported_is_recorded_as_observed(
        self, tmp_path: Path
    ) -> None:
        # The contrast: with a real observation the receipt says so, so the
        # assertion above is not satisfied by the flag being False always.
        class ReportingSpawn:
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                kwargs["spawn_out"].update(
                    {
                        "model": kwargs["model"],
                        "served_model": kwargs["model"],
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    }
                )
                return SimpleResult(stdout="## Where\n\nthe arm", returncode=0)

        runner, _git = _build(tmp_path, spawn=ReportingSpawn())

        await _dispatch(runner, [_request()])

        assert runner.artifacts[0].model_observed is True

    async def test_the_decision_id_is_published_for_the_receipt_join(
        self, tmp_path: Path
    ) -> None:
        # The tier decision is content-addressed precisely so a receipt can be
        # joined to what authorised it. #11657 found that join carried by
        # nothing on the Plan side; the same gap had been copied here.
        runner, _git = _build(tmp_path)

        await _dispatch(runner, [_request()])

        assert runner.last_decision_ids["req-1"] == runner.decisions[0].decision_id

    async def test_the_decision_map_does_not_grow_across_batches(
        self, tmp_path: Path
    ) -> None:
        # It describes THIS boundary's receipts. Carrying the previous batch's
        # ids forward would join a receipt to a decision made for another one.
        runner, _git = _build(tmp_path)

        await _dispatch(runner, [_request(request_id="req-1", key="key-1")])
        await _dispatch(runner, [_request(request_id="req-2", key="key-2")])

        assert list(runner.last_decision_ids) == ["req-2"]

    async def test_the_retained_records_are_bounded(self, tmp_path: Path) -> None:
        # This object lives for the whole run, and both accumulators were
        # unbounded and read by nothing — the same class the idempotency-key
        # set had already been bounded against.
        from implement_worker_runner import MAX_RETAINED_RECORDS

        runner, _git = _build(tmp_path)

        assert runner.decisions.maxlen == MAX_RETAINED_RECORDS
        assert runner.artifacts.maxlen == MAX_RETAINED_RECORDS

    async def test_a_refused_receipt_names_no_served_model(
        self, tmp_path: Path
    ) -> None:
        runner, _git = _build(tmp_path, spawn=SpawnRecorder(served="glm-5.3"))

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].served_model is None

    async def test_the_default_spawn_is_the_real_seam(self) -> None:
        # An injection point nobody checks is a seam in name only, which is how
        # the s51/s56/s57 sandbox wedges happened.
        from implement_worker_runner import _spawn_implement_worker

        built = ImplementWorkerRunner(
            config=HydraFlowConfig(),
            route_policy_revision=ROUTE_REVISION,
            runner=GitScript(),  # type: ignore[arg-type]
            leases=WriterLeaseRegistry(),
            base_ref=BASE_REF,
        )

        assert built.spawn is _spawn_implement_worker


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------


class TestTheWorktreeIsMeasuredThroughTheInjectedRunner:
    async def test_a_readable_worktree_measures(self, tmp_path: Path) -> None:
        runner, _git = _build(tmp_path)

        assert (await runner.measure(7)).state.head_sha == HEAD

    async def test_every_probe_runs_against_the_issues_own_worktree(
        self, tmp_path: Path
    ) -> None:
        runner, git = _build(tmp_path)
        expected = str(_config(tmp_path).workspace_path_for_issue(7))

        await runner.measure(7)

        assert {argv[2] for argv in git.calls} == {expected}

    async def test_a_missing_worktree_measures_nothing_and_runs_no_git(
        self, tmp_path: Path
    ) -> None:
        runner, git = _build(tmp_path)

        measured = await runner.measure(999)

        assert (measured.state.measured, git.calls) == (False, [])

    async def test_a_failing_probe_yields_an_unmeasured_reading(
        self, tmp_path: Path
    ) -> None:
        git = GitScript()
        git.failing.add("merge-base")
        runner, _git = _build(tmp_path, git=git)

        assert (await runner.measure(7)).state.measured is False

    async def test_the_excerpt_is_bounded_while_the_digest_is_not(
        self, tmp_path: Path
    ) -> None:
        # A change past the truncation point must still move the fence, which
        # is why the excerpt and the state are two fields of one measurement.
        long_diff = "x" * (MAX_DIFF_CHARS + 5000)
        git = GitScript()
        git.answers["diff"] = long_diff
        runner, _git = _build(tmp_path, git=git)

        measured = await runner.measure(7)

        assert (len(measured.diff_excerpt), measured.state.diff_digest) == (
            MAX_DIFF_CHARS,
            worktree_diff_digest(long_diff),
        )


# --------------------------------------------------------------------------
# The fence on the way out
# --------------------------------------------------------------------------


class TestALateWorkerIsRejectedNotDropped:
    async def test_a_commit_landing_mid_run_supersedes_the_result(
        self, tmp_path: Path
    ) -> None:
        git = GitScript()

        def land_a_commit() -> None:
            git.answers["status"] = f"# branch.oid {'c' * 40}\n# branch.head {BRANCH}\n"

        runner, _git = _build(
            tmp_path, git=git, spawn=SpawnRecorder(while_running=land_a_commit)
        )

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].status is ReceiptStatus.SUPERSEDED

    async def test_the_superseded_receipt_names_the_stale_digest(
        self, tmp_path: Path
    ) -> None:
        git = GitScript()
        runner, _git = _build(
            tmp_path,
            git=git,
            spawn=SpawnRecorder(
                while_running=lambda: git.answers.__setitem__("diff", "--- a\n+++ c\n")
            ),
        )

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is RejectionReason.WORKTREE_DIGEST_STALE

    async def test_a_reused_worktree_reports_a_branch_mismatch(
        self, tmp_path: Path
    ) -> None:
        git = GitScript()
        runner, _git = _build(
            tmp_path,
            git=git,
            spawn=SpawnRecorder(
                while_running=lambda: git.answers.__setitem__(
                    "status", f"# branch.oid {HEAD}\n# branch.head agent/issue-9\n"
                )
            ),
        )

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is RejectionReason.BRANCH_MISMATCH

    async def test_a_superseded_workers_artifact_is_discarded(
        self, tmp_path: Path
    ) -> None:
        # The difference between a fence and a warning. A superseded answer
        # describes a tree that no longer exists, and keeping it would feed the
        # next director turn a fact about the past.
        git = GitScript()
        runner, _git = _build(
            tmp_path,
            git=git,
            spawn=SpawnRecorder(
                while_running=lambda: git.answers.__setitem__("diff", "moved")
            ),
        )

        await _dispatch(runner, [_request()])

        assert list(runner.artifacts) == []

    async def test_a_driver_that_recovered_mid_run_supersedes_its_worker(
        self, tmp_path: Path
    ) -> None:
        # Epoch fencing from #11535, reused rather than re-derived.
        runner, _git = _build(tmp_path)

        receipts = await _dispatch(runner, [_request()], facts=_facts(epoch=4))

        assert receipts[0].reason_code is RejectionReason.STALE_EPOCH

    async def test_a_later_phase_attempt_supersedes_the_earlier_worker(
        self, tmp_path: Path
    ) -> None:
        runner, _git = _build(tmp_path)

        receipts = await _dispatch(runner, [_request()], facts=_facts(attempt=2))

        assert receipts[0].reason_code is RejectionReason.STALE_PHASE_ATTEMPT

    async def test_an_unmoved_slice_keeps_its_artifact(self, tmp_path: Path) -> None:
        # Non-vacuity: without this, deleting the fence's happy path would pass
        # every assertion above.
        runner, _git = _build(tmp_path)

        await _dispatch(runner, [_request()])

        assert len(runner.artifacts) == 1

    async def test_the_artifact_records_the_head_it_was_about(
        self, tmp_path: Path
    ) -> None:
        runner, _git = _build(tmp_path)

        await _dispatch(runner, [_request()])

        assert runner.artifacts[0].head_sha == HEAD


class TestAnUnarmableFenceRefusesBeforeAnySpawn:
    async def test_an_unmeasured_slice_refuses(self, tmp_path: Path) -> None:
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        receipts = await _dispatch(
            runner, [_request()], measured=WorktreeMeasurement.unmeasured()
        )

        assert receipts[0].reason_code is RejectionReason.WORKTREE_UNMEASURED

    async def test_an_unmeasured_slice_costs_nothing(self, tmp_path: Path) -> None:
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        await _dispatch(runner, [_request()], measured=WorktreeMeasurement.unmeasured())

        assert spawn.calls == []

    async def test_a_request_refused_before_the_fence_stays_replayable(
        self, tmp_path: Path
    ) -> None:
        # The key must not be claimed by work that never ran, or a repository
        # whose worktree was briefly missing could never retry that boundary.
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        await _dispatch(runner, [_request()], measured=WorktreeMeasurement.unmeasured())
        await _dispatch(runner, [_request()])

        assert len(spawn.calls) == 1


# --------------------------------------------------------------------------
# Exactly one writer
# --------------------------------------------------------------------------


class TestWritersSerializeAndReadersFanOut:
    async def test_two_writers_hold_the_lease_one_after_the_other(
        self, tmp_path: Path
    ) -> None:
        """Sequential, and the LEASE is what makes it sequential.

        The first draft asserted only that both receipts came back ACCEPTED,
        which a plain ``for`` loop delivers with the lease deleted entirely —
        nothing else contends in this scenario. What distinguishes the two is
        who holds the worktree *while each child runs*: the second writer can
        only be holding it because the first released it, which is the whole of
        "run sequentially in one issue worktree". Mutation testing killed the
        acquire and the release on other tests; this is the one that names the
        property.
        """
        leases = WriterLeaseRegistry()
        holders: list[str | None] = []
        runner, _git = _build(
            tmp_path,
            leases=leases,
            spawn=SpawnRecorder(while_running=lambda: holders.append(leases.holder(7))),
        )

        await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1"),
                _request(
                    request_id="req-2",
                    key="key-2",
                    role=WorkerRole.DEBUGGER,
                    kind=ModelRequirementKind.CAPABILITY,
                    value="high-reasoning",
                ),
            ],
        )

        assert holders == ["req-1", "req-2"]

    async def test_two_writers_in_one_batch_are_both_accepted(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        receipts = await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1"),
                _request(
                    request_id="req-2",
                    key="key-2",
                    role=WorkerRole.DEBUGGER,
                    kind=ModelRequirementKind.CAPABILITY,
                    value="high-reasoning",
                ),
            ],
        )

        assert [r.status for r in receipts] == [
            ReceiptStatus.ACCEPTED,
            ReceiptStatus.ACCEPTED,
        ]

    async def test_a_lease_held_from_an_earlier_boundary_refuses_the_writer(
        self, tmp_path: Path
    ) -> None:
        held = WriterLeaseRegistry()
        held.acquire(7, "req-from-before")
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn, leases=held)

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is RejectionReason.WRITER_LEASE_HELD

    async def test_a_refused_writer_never_starts(self, tmp_path: Path) -> None:
        held = WriterLeaseRegistry()
        held.acquire(7, "req-from-before")
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn, leases=held)

        await _dispatch(runner, [_request()])

        assert spawn.calls == []

    async def test_a_read_only_explorer_runs_while_a_writer_holds_the_lease(
        self, tmp_path: Path
    ) -> None:
        # "Read-only evidence workers may fan out; parallel writers remain
        # forbidden" — the two halves of one criterion, and this is the half a
        # single-lease-for-everyone implementation would silently break.
        held = WriterLeaseRegistry()
        held.acquire(7, "req-from-before")
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn, leases=held)

        receipts = await _dispatch(runner, [_request(role=WorkerRole.EXPLORER)])

        assert receipts[0].status is ReceiptStatus.ACCEPTED

    async def test_the_lease_is_free_again_after_a_clean_run(
        self, tmp_path: Path
    ) -> None:
        leases = WriterLeaseRegistry()
        runner, _git = _build(tmp_path, leases=leases)

        await _dispatch(runner, [_request()])

        assert leases.holder(7) is None

    async def test_the_lease_is_free_again_after_a_failed_spawn(
        self, tmp_path: Path
    ) -> None:
        # Authority ends when the worker does, whichever way it left. A lease
        # held by a dead process is the wedge a fence exists to prevent.
        leases = WriterLeaseRegistry()
        runner, _git = _build(
            tmp_path, leases=leases, spawn=ExplodingSpawn(ConnectionError("gateway"))
        )

        await _dispatch(runner, [_request()])

        assert leases.holder(7) is None

    async def test_the_lease_is_free_again_after_a_timeout(
        self, tmp_path: Path
    ) -> None:
        leases = WriterLeaseRegistry()
        runner, _git = _build(
            tmp_path, leases=leases, spawn=ExplodingSpawn(TimeoutError())
        )

        await _dispatch(runner, [_request()])

        assert leases.holder(7) is None

    async def test_an_explorer_never_takes_the_lease_at_all(
        self, tmp_path: Path
    ) -> None:
        leases = WriterLeaseRegistry()
        seen: list[str | None] = []
        runner, _git = _build(
            tmp_path,
            leases=leases,
            spawn=SpawnRecorder(while_running=lambda: seen.append(leases.holder(7))),
        )

        await _dispatch(runner, [_request(role=WorkerRole.EXPLORER)])

        assert seen == [None]

    async def test_a_writer_holds_the_lease_while_it_runs(self, tmp_path: Path) -> None:
        # Non-vacuity for the release tests: without this, never acquiring at
        # all would pass every one of them.
        leases = WriterLeaseRegistry()
        seen: list[str | None] = []
        runner, _git = _build(
            tmp_path,
            leases=leases,
            spawn=SpawnRecorder(while_running=lambda: seen.append(leases.holder(7))),
        )

        await _dispatch(runner, [_request()])

        assert seen == ["req-1"]


class TestRevokingAuthorityIsRecorded:
    def test_revoking_a_held_lease_frees_it(self, tmp_path: Path) -> None:
        leases = WriterLeaseRegistry()
        leases.acquire(7, "req-1")
        runner, _git = _build(tmp_path, leases=leases)

        runner.revoke(7, RejectionReason.HIBERNATING)

        assert leases.holder(7) is None

    def test_revoking_a_held_lease_is_written_down(self, tmp_path: Path) -> None:
        leases = WriterLeaseRegistry()
        leases.acquire(7, "req-1")
        runner, _git = _build(tmp_path, leases=leases)

        runner.revoke(7, RejectionReason.HIBERNATING)

        assert runner.revocations == [(7, "req-1")]

    def test_revoking_an_unheld_lease_records_nothing(self, tmp_path: Path) -> None:
        runner, _git = _build(tmp_path)

        runner.revoke(7, RejectionReason.STOP_FENCE)

        assert runner.revocations == []


# --------------------------------------------------------------------------
# The pre-spawn fence, the budget, and the absence of a retry
# --------------------------------------------------------------------------


class TestNothingStartsBehindAClosedFence:
    @pytest.mark.parametrize(
        "blocked",
        [
            pytest.param(RejectionReason.STOP_FENCE, id="stop"),
            pytest.param(RejectionReason.DRAINING, id="dial-cleared"),
            pytest.param(RejectionReason.HIBERNATING, id="wait"),
            pytest.param(RejectionReason.LIVE_LABEL_CHANGED, id="dragged-label"),
        ],
    )
    async def test_a_closed_fence_refuses_with_its_own_code(
        self, tmp_path: Path, blocked: RejectionReason
    ) -> None:
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        receipts = await _dispatch(runner, [_request()], fence=lambda: blocked)

        assert (receipts[0].reason_code, spawn.calls) == (blocked, [])

    async def test_a_fence_that_closes_between_two_children_stops_the_second(
        self, tmp_path: Path
    ) -> None:
        # The second child of a batch starts after the first has finished, so a
        # stop arriving during the first must stop the second.
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)
        countdown = [1]

        def closes_after_one() -> RejectionReason | None:
            if countdown[0] > 0:
                countdown[0] -= 1
                return None
            return RejectionReason.STOP_FENCE

        await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1"),
                _request(request_id="req-2", key="key-2"),
            ],
            fence=closes_after_one,
        )

        assert len(spawn.calls) == 1

    async def test_a_replayed_key_never_produces_a_second_child(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        await _dispatch(runner, [_request()])
        receipts = await _dispatch(runner, [_request(request_id="req-again")])

        assert (receipts[0].reason_code, len(spawn.calls)) == (
            RejectionReason.DUPLICATE_IDEMPOTENCY_KEY,
            1,
        )


class TestTheBudgetBoundsTheBatch:
    async def test_a_child_is_given_what_the_batch_has_left(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)

        await _dispatch(runner, [_request()])

        assert spawn.calls[0]["timeout"] == pytest.approx(
            _config(tmp_path).fable_implement_worker_timeout_seconds, abs=2.0
        )

    async def test_a_spent_batch_expires_the_rest_rather_than_starting_them(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import implement_worker_runner as module

        spawn = SpawnRecorder()
        runner, _git = _build(tmp_path, spawn=spawn)
        clock = [1000.0]
        monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

        def burn_the_budget() -> None:
            clock[0] += 10_000.0

        runner._spawn = SpawnRecorder(while_running=burn_the_budget)  # noqa: SLF001
        receipts = await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1"),
                _request(request_id="req-2", key="key-2"),
            ],
        )

        assert receipts[1].status is ReceiptStatus.EXPIRED

    async def test_a_request_that_never_ran_stays_replayable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import implement_worker_runner as module

        runner, _git = _build(tmp_path)
        clock = [1000.0]
        monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
        spawn = SpawnRecorder(while_running=lambda: clock.__setitem__(0, 99_000.0))
        runner._spawn = spawn  # noqa: SLF001

        await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1"),
                _request(request_id="req-2", key="key-2"),
            ],
        )
        clock[0] = 1000.0
        again = await _dispatch(runner, [_request(request_id="req-2", key="key-2")])

        assert again[0].status is ReceiptStatus.ACCEPTED


class TestAFencedWorkerIsNeverRetriedInPlace:
    """The retry-lineage question Gateway P4 handed forward, answered.

    ADR-0142 left a HydraFlow-side fallback driver unbuilt because *"a worker
    retry today gets a fresh dispatch_id, so lineage is gone before it could be
    cited."* This phase does not open that hole: a fenced worker that times out,
    fails, or comes back to a moved slice produces **one** terminal receipt and
    the boundary ends. The retry is the driver's own phase attempt, which is
    fenced by a token the next lease carries — so nothing here needs to cite a
    lineage it no longer has.
    """

    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            pytest.param(TimeoutError(), ReceiptStatus.EXPIRED, id="timeout"),
            pytest.param(
                ConnectionError("gateway down"), ReceiptStatus.REJECTED, id="outage"
            ),
        ],
    )
    async def test_a_failed_child_is_attempted_once(
        self, tmp_path: Path, failure: BaseException, expected: ReceiptStatus
    ) -> None:
        exploding = ExplodingSpawn(failure)
        runner, _git = _build(tmp_path, spawn=exploding)

        receipts = await _dispatch(runner, [_request()])

        assert (exploding.calls, receipts[0].status) == (1, expected)

    async def test_a_superseded_child_is_not_re_dispatched(
        self, tmp_path: Path
    ) -> None:
        """One attempt, and the outcome that makes the count mean something.

        ``len(spawn.calls) == 1`` alone is true for any single-request dispatch
        whether or not the fence exists — there is no retry path for any
        outcome. Pairing it with the status is what distinguishes "the fence
        rejected it and stopped" from "the fence was never consulted".
        """
        git = GitScript()
        spawn = SpawnRecorder(
            while_running=lambda: git.answers.__setitem__("diff", "moved")
        )
        runner, _git = _build(tmp_path, git=git, spawn=spawn)

        receipts = await _dispatch(runner, [_request()])

        assert (len(spawn.calls), receipts[0].status) == (
            1,
            ReceiptStatus.SUPERSEDED,
        )

    async def test_a_credit_exhaustion_signal_is_not_converted_into_a_refusal(
        self, tmp_path: Path
    ) -> None:
        # Factory-wide, never a worker's failure (dark-factory 2.2). Swallowing
        # it would burn attempt budget against an exhausted billing signal.
        from exception_classify import CreditExhaustedError

        runner, _git = _build(
            tmp_path, spawn=ExplodingSpawn(CreditExhaustedError("out of credit"))
        )

        with pytest.raises(CreditExhaustedError):
            await _dispatch(runner, [_request()])


# --------------------------------------------------------------------------
# The prompt, and the hibernation adapter
# --------------------------------------------------------------------------


class TestTheWorkerIsToldItsBound:
    def test_the_prompt_names_the_snapshot_it_is_about(self) -> None:
        rendered = build_implement_worker_prompt(
            role="implementer",
            task_contract="fix the retry",
            issue_goal="make the widget faster",
            issue_number=7,
            worktree=_measurement(),
        )

        assert HEAD in rendered and BRANCH in rendered

    def test_the_prompt_forbids_committing_and_pushing(self) -> None:
        # AC 6 stated to the worker as well as enforced around it.
        rendered = build_implement_worker_prompt(
            role="debugger",
            task_contract="find the leak",
            issue_goal="make the widget faster",
            issue_number=7,
            worktree=_measurement(),
        )

        assert "no ability to commit, push" in rendered

    def test_a_truncated_diff_says_so(self) -> None:
        # A worker shown the first 24 000 characters of a long diff will reason
        # as though that is the whole change unless told otherwise.
        long_measurement = WorktreeMeasurement(
            state=_measurement().state, diff_excerpt="y" * MAX_DIFF_CHARS
        )
        rendered = build_implement_worker_prompt(
            role="implementer",
            task_contract="fix the retry",
            issue_goal="make the widget faster",
            issue_number=7,
            worktree=long_measurement,
        )

        assert "TRUNCATED" in rendered

    def test_an_empty_diff_is_described_as_a_real_state(self) -> None:
        empty = WorktreeMeasurement(state=_measurement().state, diff_excerpt="")
        rendered = build_implement_worker_prompt(
            role="implementer",
            task_contract="fix the retry",
            issue_goal="make the widget faster",
            issue_number=7,
            worktree=empty,
        )

        assert "no uncommitted or committed change" in rendered
