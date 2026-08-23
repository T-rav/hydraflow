"""The Implement canary's pure decision layer (#11542, ADR-0137 P4).

Five things are decided in :mod:`implement_broker` and each has its own class
below: the bound, the fence, the measurement, the single writer, and
hibernation. Everything here is pure, so every test drives the real function
with real inputs — there is no port to fake and nothing to mock.

The fence is the load-bearing one. Its job is to make a late or superseded
worker's result **rejected**, and a rejection is only worth anything if it can
be told apart from the result being quietly dropped, so every fence test names
the breach it expects rather than merely asserting that something went wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from driver_contracts import (
    WORKER_CATALOG,
    DriverLease,
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    RejectionReason,
    WorkerDispatchRequest,
    WorkerRole,
    WriteScope,
)
from implement_broker import (
    FENCE_REJECTIONS,
    UNMEASURED_DIGEST,
    WORKTREE_PROBE_TOKENS,
    FenceBreach,
    Hibernation,
    WorktreeState,
    WriterLeaseRegistry,
    check_worker_fence,
    hibernation_reason,
    hibernation_refusal,
    implement_canary_armed,
    implement_canary_covers,
    implement_roles_for_implement_phase,
    needs_writer_lease,
    resolve_implement_model,
    worktree_diff_digest,
    worktree_probes,
    worktree_state_from_reads,
    writer_lease_for,
)
from plan_broker import PlanRouteOutcome, PlanRouteReason, PlanRouteSource

READY_LABEL = "hydraflow-ready"
BRANCH = "agent/issue-7"
BASE = "a" * 40
HEAD = "b" * 40


class _Dials:
    """A stand-in for the two config fields the bound reads. Nothing else."""

    def __init__(self, repo: str, canary: str) -> None:
        self.repo = repo
        self.fable_implement_canary_repo = canary


def _lease(*, epoch: int = 3, attempt: int = 1, owner: str = "drv-7") -> DriverLease:
    return DriverLease(
        driver_id=owner,
        epoch=epoch,
        repo_slug="acme/widgets",
        issue_number=7,
        phase=DriverPhase.IMPLEMENT,
        expected_stage_label=READY_LABEL,
        phase_attempt=attempt,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def _tree(**overrides: str) -> WorktreeState:
    fields: dict[str, str] = {
        "branch": BRANCH,
        "base_sha": BASE,
        "head_sha": HEAD,
        "diff_digest": worktree_diff_digest("--- a\n+++ b\n"),
    }
    fields.update(overrides)
    return WorktreeState(**fields)  # type: ignore[arg-type]


def _judge(
    *,
    minted: WorktreeState | None = None,
    observed: WorktreeState | None = None,
    owner: str = "drv-7",
    epoch: int = 3,
    attempt: int = 1,
    label: str = READY_LABEL,
) -> FenceBreach:
    """Run the fence with everything at its nominal value bar the overrides."""
    return check_worker_fence(
        minted=minted or _tree(),
        observed=observed or _tree(),
        lease=_lease(),
        driver_id=owner,
        driver_epoch=epoch,
        driver_phase_attempt=attempt,
        live_stage_label=label,
    )


def _request(
    *,
    role: WorkerRole = WorkerRole.IMPLEMENTER,
    kind: ModelRequirementKind = ModelRequirementKind.LITERAL_FAMILY,
    value: str = "claude-sonnet",
) -> WorkerDispatchRequest:
    return WorkerDispatchRequest(
        request_id="req-1",
        driver_id="drv-7",
        epoch=3,
        phase_attempt=1,
        worker_role=role,
        model_requirement=ModelRequirement(kind=kind, value=value),
        task_contract="fix the double-counted retry",
        reason="the review found a double increment",
        expected_route_policy_revision="route-v1",
        idempotency_key="key-7",
    )


# --------------------------------------------------------------------------
# The bound
# --------------------------------------------------------------------------


class TestTheBoundIsOnePredicate:
    @pytest.mark.parametrize(
        "repo",
        [
            pytest.param("acme/widgets", id="a-real-repository"),
            pytest.param("", id="an-unidentifiable-repository"),
        ],
    )
    def test_an_empty_dial_covers_nothing(self, repo: str) -> None:
        """The armed clause, and the second case is the one that isolates it.

        With a real repository, deleting ``if armed is None: return False``
        still answers ``False`` — via the repo comparison, which is ``False``
        for its own reason. The clause is invisible behind it. With a
        repository whose own identity is *also* unparseable, deleting the
        clause leaves ``canonicalize_repo("") == None``, i.e. ``None == None``,
        i.e. **True**: a disarmed dial covering every boundary. That is the
        failure the clause exists to prevent, and only the second case can see
        it. Found by mutation testing, which killed the first case and
        survived on nothing else.
        """
        assert (
            implement_canary_covers(_Dials(repo, ""), phase=DriverPhase.IMPLEMENT)
            is False
        )

    def test_the_named_repository_at_implement_is_covered(self) -> None:
        assert (
            implement_canary_covers(
                _Dials("acme/widgets", "acme/widgets"), phase=DriverPhase.IMPLEMENT
            )
            is True
        )

    def test_another_repository_is_outside_the_bound(self) -> None:
        assert (
            implement_canary_covers(
                _Dials("acme/widgets", "acme/other"), phase=DriverPhase.IMPLEMENT
            )
            is False
        )

    @pytest.mark.parametrize(
        "elsewhere",
        [
            pytest.param(DriverPhase.TRIAGE, id="triage"),
            pytest.param(DriverPhase.PLAN, id="plan"),
            pytest.param(DriverPhase.REVIEW, id="review"),
            pytest.param(DriverPhase.HITL, id="hitl"),
            pytest.param(None, id="no-phase"),
        ],
    )
    def test_every_other_phase_stays_classic(
        self, elsewhere: DriverPhase | None
    ) -> None:
        # "Independent review remains Classic" as a property of this function
        # rather than of every caller remembering to check, which is what makes
        # #11542's seventh acceptance criterion enforceable.
        assert (
            implement_canary_covers(
                _Dials("acme/widgets", "acme/widgets"), phase=elsewhere
            )
            is False
        )

    @pytest.mark.parametrize(
        "lossy",
        [
            pytest.param("acme-widgets", id="runtime-slug"),
            pytest.param("widgets", id="bare-name"),
        ],
    )
    def test_a_lossy_identity_arms_nothing(self, lossy: str) -> None:
        # ADR-0139 D2's refusal in both directions: a slug typed into the dial
        # arms nothing, and a slug-derived repository cannot fall into an armed
        # canary.
        assert implement_canary_armed(_Dials("acme/widgets", lossy)) is False

    def test_the_menu_comes_from_the_catalog(self) -> None:
        # Derived, not listed, so the canary's menu and the admission rule
        # table cannot disagree about what an IMPLEMENT boundary may ask for.
        assert implement_roles_for_implement_phase() == frozenset(
            role
            for role, entry in WORKER_CATALOG.items()
            if DriverPhase.IMPLEMENT in entry.allowed_phases
        )

    def test_the_menu_carries_both_correction_roles(self) -> None:
        # The issue's first acceptance criterion names implementers AND
        # policy-approved debuggers; a menu missing either would satisfy every
        # derivation test above while delivering half the phase.
        assert {WorkerRole.IMPLEMENTER, WorkerRole.DEBUGGER} <= (
            implement_roles_for_implement_phase()
        )

    def test_the_reviewer_is_not_on_the_menu(self) -> None:
        assert WorkerRole.REVIEWER not in implement_roles_for_implement_phase()


# --------------------------------------------------------------------------
# The fence
# --------------------------------------------------------------------------


class TestAnUnmovedSliceIsAdmissible:
    def test_the_nominal_case_passes(self) -> None:
        assert _judge() is FenceBreach.NONE

    def test_a_blank_live_label_does_not_breach(self) -> None:
        # A driver whose state maps to no label yields "", and refusing on that
        # would fence every worker on a state nobody labelled.
        assert _judge(label="") is FenceBreach.NONE


class TestOwnershipBreachesComeFirst:
    def test_another_driver_is_ownership_not_staleness(self) -> None:
        # Reported as a distinct breach so a misrouted result never inflates
        # the ordinary-churn counter ADR-0137 B5 reads.
        assert _judge(owner="drv-9") is FenceBreach.DRIVER_REPLACED

    def test_a_recovered_driver_supersedes_its_own_worker(self) -> None:
        assert _judge(epoch=4) is FenceBreach.EPOCH_SUPERSEDED

    def test_a_later_attempt_supersedes_the_earlier_one(self) -> None:
        assert _judge(attempt=2) is FenceBreach.PHASE_ATTEMPT_SUPERSEDED

    def test_a_dragged_label_preempts_the_worker(self) -> None:
        assert _judge(label="hydraflow-hitl") is FenceBreach.LIVE_LABEL_CHANGED

    def test_ownership_outranks_a_moved_worktree(self) -> None:
        # Both moved. The reported code must be the one that tells an operator
        # what to fix, and "another driver owns this issue" is not fixed by
        # looking at a diff.
        breach = _judge(owner="drv-9", observed=_tree(head_sha="c" * 40))

        assert breach is FenceBreach.DRIVER_REPLACED


class TestAMovedWorktreeIsRejectedByName:
    def test_a_reused_worktree_reports_the_branch(self) -> None:
        breach = _judge(observed=_tree(branch="agent/issue-9"))

        assert breach is FenceBreach.BRANCH_MISMATCH

    def test_a_rebase_reports_the_base(self) -> None:
        breach = _judge(observed=_tree(base_sha="d" * 40))

        assert breach is FenceBreach.BASE_MOVED

    def test_a_landed_commit_reports_the_head(self) -> None:
        breach = _judge(observed=_tree(head_sha="e" * 40))

        assert breach is FenceBreach.HEAD_MOVED

    def test_changed_content_without_a_commit_reports_the_diff(self) -> None:
        moved = _tree(diff_digest=worktree_diff_digest("--- a\n+++ different\n"))

        assert _judge(observed=moved) is FenceBreach.DIFF_DIGEST_STALE

    def test_a_reused_worktree_outranks_a_moved_head(self) -> None:
        # Coarsest first: a worktree pointed at another issue's branch needs a
        # different fix from a commit landing under a worker, and reporting the
        # commit would send an operator to read the wrong diff.
        breach = _judge(observed=_tree(branch="agent/issue-9", head_sha="f" * 40))

        assert breach is FenceBreach.BRANCH_MISMATCH


class TestAnUnmeasuredSliceIsUnverifiedNeverUnchanged:
    def test_an_unmeasured_mint_refuses(self) -> None:
        assert _judge(minted=WorktreeState.unmeasured()) is FenceBreach.UNMEASURED

    def test_an_unmeasured_observation_refuses(self) -> None:
        assert _judge(observed=WorktreeState.unmeasured()) is FenceBreach.UNMEASURED

    def test_two_unmeasured_sides_do_not_verify_each_other(self) -> None:
        # ADR-0137 S4's rule at a second boundary. Without the explicit check,
        # two identical "unmeasured" strings compare equal and a fence that
        # measured nothing would verify everything — the exact fail-open shape
        # finding F2 condemns.
        breach = _judge(
            minted=WorktreeState.unmeasured(), observed=WorktreeState.unmeasured()
        )

        assert breach is FenceBreach.UNMEASURED

    def test_a_blank_token_is_also_unmeasured(self) -> None:
        assert _judge(observed=_tree(head_sha="")) is FenceBreach.UNMEASURED

    def test_a_fully_read_tree_reports_itself_measured(self) -> None:
        assert _tree().measured is True


class TestEveryBreachCarriesADeterministicCode:
    def test_every_breach_but_none_maps_to_a_rejection(self) -> None:
        # A table rather than branches, so a new breach fails loudly here
        # instead of defaulting to a plausible code.
        assert set(FENCE_REJECTIONS) == set(FenceBreach) - {FenceBreach.NONE}

    @pytest.mark.parametrize(
        ("breach", "code"),
        [
            pytest.param(
                FenceBreach.DRIVER_REPLACED,
                RejectionReason.DRIVER_IDENTITY_MISMATCH,
                id="driver",
            ),
            pytest.param(
                FenceBreach.EPOCH_SUPERSEDED,
                RejectionReason.STALE_EPOCH,
                id="epoch",
            ),
            pytest.param(
                FenceBreach.PHASE_ATTEMPT_SUPERSEDED,
                RejectionReason.STALE_PHASE_ATTEMPT,
                id="phase-attempt",
            ),
            pytest.param(
                FenceBreach.LIVE_LABEL_CHANGED,
                RejectionReason.LIVE_LABEL_CHANGED,
                id="label",
            ),
            pytest.param(
                FenceBreach.UNMEASURED,
                RejectionReason.WORKTREE_UNMEASURED,
                id="unmeasured",
            ),
            pytest.param(
                FenceBreach.BRANCH_MISMATCH,
                RejectionReason.BRANCH_MISMATCH,
                id="branch",
            ),
            pytest.param(
                FenceBreach.BASE_MOVED,
                RejectionReason.WORKTREE_DIGEST_STALE,
                id="base",
            ),
            pytest.param(
                FenceBreach.HEAD_MOVED,
                RejectionReason.WORKTREE_DIGEST_STALE,
                id="head",
            ),
            pytest.param(
                FenceBreach.DIFF_DIGEST_STALE,
                RejectionReason.WORKTREE_DIGEST_STALE,
                id="diff",
            ),
        ],
    )
    def test_every_breach_keeps_its_code(
        self, breach: FenceBreach, code: RejectionReason
    ) -> None:
        # #11542's fifth acceptance criterion names stale digest and branch
        # mismatch specifically; pinning the codes keeps the evidence readable
        # against the criterion that asked for it.
        assert FENCE_REJECTIONS[breach] is code

    def test_a_branch_mismatch_is_not_reported_as_a_stale_digest(self) -> None:
        assert (
            FENCE_REJECTIONS[FenceBreach.BRANCH_MISMATCH]
            is not FENCE_REJECTIONS[FenceBreach.HEAD_MOVED]
        )


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------


class TestTheMeasurementIsPureAndTotal:
    def test_the_probe_set_is_exactly_three_reads(self) -> None:
        tokens = [token for token, _argv in worktree_probes("origin/staging")]

        assert tokens == list(WORKTREE_PROBE_TOKENS)

    def test_the_base_probe_names_the_ref_it_was_given(self) -> None:
        # ``@{upstream}`` is not a fence: a branch that has never been pushed
        # has none, and a probe that silently answered nothing there would mint
        # an unmeasured lease at the first implement attempt.
        argv = dict(worktree_probes("origin/staging"))["base"]

        assert argv == ("merge-base", "HEAD", "origin/staging")

    def test_the_status_probe_carries_branch_and_head_in_one_read(self) -> None:
        # One read, so both tokens describe one moment.
        argv = dict(worktree_probes("origin/main"))["status"]

        assert argv == ("status", "--porcelain=v2", "--branch")

    def test_a_full_reading_parses_into_a_measured_state(self) -> None:
        parsed = worktree_state_from_reads(
            {
                "status": f"# branch.oid {HEAD}\n# branch.head {BRANCH}\n",
                "base": f"{BASE}\n",
                "diff": "--- a\n+++ b\n",
            }
        )

        assert parsed == _tree()

    def test_a_clean_worktree_still_digests_to_a_real_token(self) -> None:
        # An empty diff is a real, common reading. Treating it as unmeasured
        # would refuse every worker on a branch with nothing uncommitted.
        parsed = worktree_state_from_reads(
            {
                "status": f"# branch.oid {HEAD}\n# branch.head {BRANCH}\n",
                "base": BASE,
                "diff": "",
            }
        )

        assert parsed.measured is True

    def test_a_missing_diff_probe_is_unmeasured(self) -> None:
        parsed = worktree_state_from_reads(
            {"status": f"# branch.oid {HEAD}\n# branch.head {BRANCH}\n", "base": BASE}
        )

        assert parsed.diff_digest == UNMEASURED_DIGEST

    def test_an_empty_reading_yields_an_unmeasured_state(self) -> None:
        assert worktree_state_from_reads({}).measured is False

    def test_unparseable_status_output_does_not_raise(self) -> None:
        # Total on purpose: this runs on a live dispatch path, and an exception
        # thrown while measuring a fence would be an incident rather than a
        # refusal an operator can read.
        parsed = worktree_state_from_reads(
            {"status": "fatal: not a git repository", "base": "", "diff": ""}
        )

        assert parsed.measured is False

    def test_different_diffs_digest_differently(self) -> None:
        assert worktree_diff_digest("one") != worktree_diff_digest("two")

    def test_the_digest_names_the_algorithm_that_made_it(self) -> None:
        # Distinctness alone is satisfied by any deterministic hash. The
        # prefixed, fixed-width form is what makes a digest on a receipt
        # comparable to one in a prompt or a log without a decoder ring.
        digest = worktree_diff_digest("--- a\n+++ b\n")

        assert digest.startswith("sha256:") and len(digest) == len("sha256:") + 32


class TestTheMintedLeaseCarriesTheMeasurement:
    def test_the_lease_takes_the_drivers_identity(self) -> None:
        minted = writer_lease_for(_lease(), _tree())

        assert (minted.driver_id, minted.epoch) == ("drv-7", 3)

    def test_the_lease_carries_the_measured_digests(self) -> None:
        # The replacement for #11537's ``"unobserved"`` placeholders, which is
        # what ADR-0137 explicitly left to this phase.
        minted = writer_lease_for(_lease(), _tree())

        assert (minted.worktree_base_digest, minted.worktree_head_digest) == (
            BASE,
            HEAD,
        )

    def test_an_unheld_lease_names_no_holder(self) -> None:
        assert writer_lease_for(_lease(), _tree()).is_held is False

    def test_a_held_lease_names_its_holder(self) -> None:
        minted = writer_lease_for(_lease(), _tree(), holder_request_id="req-1")

        assert minted.holder_request_id == "req-1"


# --------------------------------------------------------------------------
# The single writer
# --------------------------------------------------------------------------


class TestExactlyOneWriterHoldsAWorktree:
    def test_the_first_request_takes_it(self) -> None:
        assert WriterLeaseRegistry().acquire(7, "req-1") is True

    def test_a_second_request_is_refused_while_it_is_held(self) -> None:
        registry = WriterLeaseRegistry()
        registry.acquire(7, "req-1")

        assert registry.acquire(7, "req-2") is False

    def test_re_acquiring_is_idempotent_for_the_holder(self) -> None:
        # A retry of the same request within one batch is the same logical
        # writer; refusing it would make one writer look like two.
        registry = WriterLeaseRegistry()
        registry.acquire(7, "req-1")

        assert registry.acquire(7, "req-1") is True

    def test_releasing_frees_it_for_the_next_request(self) -> None:
        registry = WriterLeaseRegistry()
        registry.acquire(7, "req-1")
        registry.release(7, "req-1")

        assert registry.acquire(7, "req-2") is True

    def test_a_non_holder_cannot_release_it(self) -> None:
        registry = WriterLeaseRegistry()
        registry.acquire(7, "req-1")
        registry.release(7, "req-2")

        assert registry.holder(7) == "req-1"

    def test_two_issues_do_not_contend(self) -> None:
        # Two issues have two worktrees, and a writer in each races nothing. A
        # global single writer would be a throughput regression wearing a fence.
        registry = WriterLeaseRegistry()
        registry.acquire(7, "req-1")

        assert registry.acquire(9, "req-2") is True

    def test_revoking_reports_the_holder_it_displaced(self) -> None:
        # Reported rather than merely performed, because ADR-0137 B5 counts
        # ownership events and a revocation nobody wrote down cannot be told
        # from a lease that was never held.
        registry = WriterLeaseRegistry()
        registry.acquire(7, "req-1")

        assert registry.revoke(7) == "req-1"

    def test_revoking_an_unheld_worktree_reports_nothing(self) -> None:
        assert WriterLeaseRegistry().revoke(7) is None

    def test_a_revoked_worktree_is_free(self) -> None:
        registry = WriterLeaseRegistry()
        registry.acquire(7, "req-1")
        registry.revoke(7)

        assert registry.holder(7) is None


class TestOnlyWorktreeWritersTakeTheLease:
    @pytest.mark.parametrize(
        "writer",
        [
            pytest.param(WorkerRole.IMPLEMENTER, id="implementer"),
            pytest.param(WorkerRole.DEBUGGER, id="debugger"),
        ],
    )
    def test_a_write_capable_role_needs_it(self, writer: WorkerRole) -> None:
        assert needs_writer_lease(writer) is True

    @pytest.mark.parametrize(
        "reader",
        [
            pytest.param(WorkerRole.EXPLORER, id="explorer"),
            pytest.param(WorkerRole.REVIEWER, id="reviewer"),
            pytest.param(WorkerRole.TEST_ADEQUACY, id="test-adequacy"),
        ],
    )
    def test_a_read_only_role_may_fan_out(self, reader: WorkerRole) -> None:
        # "Read-only evidence workers may fan out" is this, and it is derived
        # from the catalog rather than from a second list of role names.
        assert needs_writer_lease(reader) is False

    def test_the_question_is_answered_by_the_catalog(self) -> None:
        assert {role for role in WorkerRole if needs_writer_lease(role)} == {
            role
            for role, entry in WORKER_CATALOG.items()
            if entry.write_scope is WriteScope.ISSUE_WORKTREE
        }


# --------------------------------------------------------------------------
# Hibernation
# --------------------------------------------------------------------------


class TestHibernationNamesTheThreeWaits:
    @pytest.mark.parametrize(
        ("state", "wait"),
        [
            pytest.param("PARKED", Hibernation.CI_WAIT, id="ci"),
            pytest.param("DIAGNOSE", Hibernation.DIAGNOSTIC, id="diagnostic"),
            pytest.param("HITL_WAIT", Hibernation.HITL_WAIT, id="human"),
        ],
    )
    def test_each_wait_is_recognised_by_name(
        self, state: str, wait: Hibernation
    ) -> None:
        # #11542's fourth acceptance criterion lists exactly three waits, and
        # each is reported distinctly so an operator reading a refused batch
        # knows whether to look at CI, at a diagnostic, or at a person.
        assert hibernation_reason(state) is wait

    @pytest.mark.parametrize(
        "working",
        [
            pytest.param("READY", id="implementing"),
            pytest.param("REVIEW", id="reviewing"),
            pytest.param("PLAN", id="planning"),
            pytest.param("HITL_APPLY", id="applying-a-correction"),
        ],
    )
    def test_a_working_driver_is_not_hibernating(self, working: str) -> None:
        # ``HITL_APPLY`` is the interesting one: it shares a label with
        # ``HITL_WAIT`` and means the opposite — work is happening.
        assert hibernation_reason(working) is None


class TestTheHibernationAdapterSpeaksOneCode:
    @pytest.mark.parametrize(
        "waiting",
        [
            pytest.param("PARKED", id="ci"),
            pytest.param("DIAGNOSE", id="diagnostic"),
            pytest.param("HITL_WAIT", id="human"),
        ],
    )
    def test_every_wait_reports_the_same_deterministic_code(self, waiting: str) -> None:
        assert hibernation_refusal(waiting) is RejectionReason.HIBERNATING

    def test_a_working_driver_reports_nothing(self) -> None:
        assert hibernation_refusal("READY") is None


# --------------------------------------------------------------------------
# The tier choice, shared with the Plan canary
# --------------------------------------------------------------------------


class TestTheTierChoiceIsTheSharedResolver:
    def test_a_literal_family_resolves_to_the_catalogued_id(self) -> None:
        decision = resolve_implement_model(
            _request(),
            phase=DriverPhase.IMPLEMENT,
            route_policy_revision="route-v1",
            lane_serves_anthropic=True,
        )

        assert decision.served_model == "claude-sonnet-4-6"

    def test_the_debuggers_capability_class_resolves_through_the_table(self) -> None:
        # The catalogued debugger asks for ``high-reasoning`` rather than a
        # family, which is the "policy-selected Opus/Sonnet debugger" the issue
        # names — and the table is the thing an operator reads to know which.
        decision = resolve_implement_model(
            _request(
                role=WorkerRole.DEBUGGER,
                kind=ModelRequirementKind.CAPABILITY,
                value="high-reasoning",
            ),
            phase=DriverPhase.IMPLEMENT,
            route_policy_revision="route-v1",
            lane_serves_anthropic=True,
        )

        assert (decision.served_model, decision.source) == (
            "claude-opus-4-7",
            PlanRouteSource.CAPABILITY_TABLE,
        )

    def test_a_lane_that_cannot_serve_anthropic_rejects_before_any_spawn(self) -> None:
        decision = resolve_implement_model(
            _request(),
            phase=DriverPhase.IMPLEMENT,
            route_policy_revision="route-v1",
            lane_serves_anthropic=False,
        )

        assert (decision.outcome, decision.reason) == (
            PlanRouteOutcome.REJECTED,
            PlanRouteReason.LITERAL_FAMILY_UNSATISFIABLE,
        )

    def test_a_plan_phase_request_is_refused_with_the_implement_vocabulary(
        self,
    ) -> None:
        # The refusal reads "this was not an implement boundary" rather than
        # borrowing the Plan canary's wording, because the two facts send an
        # operator to different places.
        decision = resolve_implement_model(
            _request(),
            phase=DriverPhase.PLAN,
            route_policy_revision="route-v1",
            lane_serves_anthropic=True,
        )

        assert decision.reason is PlanRouteReason.PHASE_NOT_IMPLEMENT

    def test_a_role_the_phase_does_not_catalogue_is_refused(self) -> None:
        decision = resolve_implement_model(
            _request(role=WorkerRole.PLANNER),
            phase=DriverPhase.IMPLEMENT,
            route_policy_revision="route-v1",
            lane_serves_anthropic=True,
        )

        assert decision.reason is PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_IMPLEMENT

    def test_the_two_canaries_share_one_tier_table(self) -> None:
        # The whole reason the resolver is parameterised rather than forked: a
        # second copy would carry a second answer to "which id is
        # claude-sonnet", and the table is code-owned precisely so there is one.
        from plan_broker import resolve_plan_model

        implement = resolve_implement_model(
            _request(role=WorkerRole.EXPLORER),
            phase=DriverPhase.IMPLEMENT,
            route_policy_revision="route-v1",
            lane_serves_anthropic=True,
        )
        plan = resolve_plan_model(
            _request(role=WorkerRole.EXPLORER),
            phase=DriverPhase.PLAN,
            route_policy_revision="route-v1",
            lane_serves_anthropic=True,
        )

        assert implement.served_model == plan.served_model

    def test_the_decision_names_the_catalog_revision_it_was_made_against(self) -> None:
        from plan_broker import PLAN_TIER_CATALOG_REVISION

        decision = resolve_implement_model(
            _request(),
            phase=DriverPhase.IMPLEMENT,
            route_policy_revision="route-v1",
            lane_serves_anthropic=True,
        )

        assert decision.catalog_revision == PLAN_TIER_CATALOG_REVISION


class TestBrokeredWritersMintInsideTheAuthorizationBoundary:
    """The boundary #11542 relies on, asserted rather than assumed.

    A brokered child's gateway key is minted inside ``run_lightweight_agent``,
    which resolves a governed route with ``principal_id=source``; the actuator
    passes the worker's catalogued role as ``source``, and
    ``routing_policy.canonical_worker_role`` matches a ``WorkerRole`` value
    exactly. So a brokered writer mints a route-**bound** v2 key attributable to
    its own worker account wherever the enforcement canary is armed — the same
    path every other governed spawn takes.

    That chain has one link a future edit could break silently: a role whose
    value stopped being a canonical principal would mint **unbound** with no
    error anywhere. This pins it.
    """

    @pytest.mark.parametrize(
        "role",
        sorted(implement_roles_for_implement_phase(), key=lambda r: r.value),
        ids=lambda r: r.value,
    )
    def test_every_dispatchable_role_is_a_canonical_principal(
        self, role: WorkerRole
    ) -> None:
        from hydraflow_gateway.routing_policy import canonical_worker_role

        assert canonical_worker_role(role.value) is role

    def test_a_loop_shaped_source_would_not_be(self) -> None:
        # The non-vacuity half: the assertion above is only meaningful because
        # this join can fail.
        from hydraflow_gateway.routing_policy import canonical_worker_role

        assert canonical_worker_role("implement_worker_runner") is None
