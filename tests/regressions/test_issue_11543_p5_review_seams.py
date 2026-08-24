"""The P5 review seams that were green while guarding nothing (#11543).

Four modules shipped for ADR-0137 P5 — ``review_broker``, ``review_authority``,
``review_evidence`` and the vitals/conformance seam — and an independent review
found that several of their load-bearing guards could not fire. Each defect
below shares one shape, and it is the shape this repository spent the week
closing (#11669's veto inert for 104 days, #11670's guard never added, #11673's
membership check that stopped seeing its subject):

    a guard whose subject cannot reach it, documented as intended, and pinned
    by a test that passes for a reason other than the one it names.

That last clause is what makes these worth a regression file rather than a
patch. An un-pinned fail-open is a bug; a *pinned* one is a bug plus a
tripwire against fixing it — the next reader stops looking, and the correction
reads as the regression. So each test here states the defect as it was
reproduced, not the fix as it was written.

Offline by construction: every check is a pure function of a value.
"""

from __future__ import annotations

import itertools
from collections import deque
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ConfigDict, Field, ValidationError, computed_field

from driver_contracts import (
    WORKER_CATALOG,
    DriverLease,
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    RejectionReason,
    WorkerDispatchRequest,
    WorkerRole,
    WriterLease,
    WriteScope,
    admit_dispatch,
)
from models import ReviewVerdict
from review_authority import (
    AdjudicationReason,
    ReviewFinding,
    ReviewProposal,
    adjudicate,
)
from review_broker import (
    CANARY_PHASE,
    review_roles_for_review_phase,
    reviewer_independence_refusal,
)
from review_evidence import CANONICAL_FIELDS, ReviewEvidence, build_review_evidence

_PERMISSIVE = {"ci_green": True, "hitl_required": False, "reviewer_independent": True}


class TestTheSelfReviewFenceIsReachable:
    """Finding 1. The fence fired only when its subject volunteered the proof.

    ``WorkerDispatchRequest.requesting_spawn_id`` defaults to ``None`` and
    nothing in ``src/`` writes it — the only production producer is the director
    model's own JSON. ``reviewer_independence_refusal`` admitted ``None``, so
    the sole request the fence could ever refuse was one where the party being
    fenced supplied the value that refused it.
    """

    @pytest.mark.parametrize("absent", [None, "", "  "])
    def test_a_fenced_role_that_cannot_state_its_lineage_is_refused(
        self, absent: str | None
    ) -> None:
        assert (
            reviewer_independence_refusal(
                role=WorkerRole.REVIEWER,
                requesting_spawn_id=absent,
                implementer_spawn_ids=["spawn-impl-1"],
            )
            is RejectionReason.LINEAGE_UNKNOWN
        )

    def test_the_refusal_is_not_the_self_review_code(self) -> None:
        """The two say different things to an operator and must stay apart.

        ``SELF_REVIEW_FORBIDDEN`` asserts a fact — this requester implemented
        the change — that an absent lineage cannot establish. Folding them
        would make a caller that forgot to stamp provenance indistinguishable
        from a worker caught grading its own homework.
        """
        stamped = reviewer_independence_refusal(
            role=WorkerRole.REVIEWER,
            requesting_spawn_id="spawn-impl-1",
            implementer_spawn_ids=["spawn-impl-1"],
        )
        assert stamped is RejectionReason.SELF_REVIEW_FORBIDDEN

    def test_an_unfenced_role_is_untouched(self) -> None:
        """Non-vacuity in the other direction: a director's own depth-1
        explorer legitimately has no parent spawn, and refusing it would be the
        fence spreading past its subject."""
        assert (
            reviewer_independence_refusal(
                role=WorkerRole.EXPLORER,
                requesting_spawn_id=None,
                implementer_spawn_ids=["spawn-impl-1"],
            )
            is None
        )


class TestEveryJudgeAtReviewIsIndependent:
    """Finding 2. Four roles are legal at REVIEW; one was fenced.

    ``ARCHITECT`` and ``TEST_ADEQUACY`` carried no independence flag, so an
    implementer's lineage could request either at REVIEW and judge its own
    work — and a unit test asserted that hole as correct behaviour.
    """

    def test_the_rule_is_derived_from_the_catalogue(self) -> None:
        read_only_at_review = {
            role
            for role, entry in WORKER_CATALOG.items()
            if DriverPhase.REVIEW in entry.allowed_phases
            and entry.write_scope is WriteScope.NONE
        }
        assert read_only_at_review, "no subject — the rule below is vacuous"
        for role in read_only_at_review:
            assert WORKER_CATALOG[role].independent_of_implementer is True, role

    @pytest.mark.parametrize(
        "role", [WorkerRole.ARCHITECT, WorkerRole.TEST_ADEQUACY, WorkerRole.REVIEWER]
    )
    def test_each_judge_is_refused_from_the_implementers_lineage(
        self, role: WorkerRole
    ) -> None:
        """The property the derived rule buys, spelled out per role.

        Named explicitly here — and ONLY here — because the point of the
        regression is the three roles, and a derived assertion alone would
        still pass if the catalogue lost two of them.
        """
        assert (
            reviewer_independence_refusal(
                role=role,
                requesting_spawn_id="spawn-impl-1",
                implementer_spawn_ids=["spawn-impl-1"],
            )
            is RejectionReason.SELF_REVIEW_FORBIDDEN
        )


class TestTheReviewDialArmsNoWriter:
    """Finding 3. A read-only canary that armed a writer.

    ``fable_review_canary_repo`` reads as a brokered *reviewer* canary, but the
    menu was derived from phase alone and the catalogue legalises ``DEBUGGER``
    at REVIEW with ``ISSUE_WORKTREE`` write scope. Arming it therefore widened
    the write boundary without ``fable_implement_canary_repo`` being touched —
    breaking "widen one role boundary at a time", which is the entire reason
    there are three dials.
    """

    def test_every_role_on_the_menu_writes_nothing(self) -> None:
        for role in review_roles_for_review_phase():
            assert WORKER_CATALOG[role].write_scope is WriteScope.NONE, role

    def test_the_writer_it_excludes_really_is_catalogued_at_review(self) -> None:
        """Negative control: with no write-scoped REVIEW role in the catalogue
        the filter is a no-op and the assertion above proves nothing."""
        excluded = {
            role
            for role, entry in WORKER_CATALOG.items()
            if CANARY_PHASE in entry.allowed_phases
            and entry.write_scope is not WriteScope.NONE
        }
        assert excluded, "nothing to exclude — the menu filter is vacuous"
        assert not (excluded & review_roles_for_review_phase())


class TestAFailedShaLookupCannotApprove:
    """Finding 4. A partial snapshot pair silently approved.

    ``if evidence_head_sha and current_head_sha and ...`` treated one supplied
    side as "not checked". The live risk is a caller whose head-sha lookup just
    failed passing ``current_head_sha=""`` and getting ``APPROVE`` — the
    bounded-slice rule switched off exactly when the repository state is
    unknown. The test that guarded it asserted ``verdict is APPROVE``, which is
    also what "treated as a match" produces, so it could not fail for the
    reason it named.
    """

    @pytest.mark.parametrize(
        "supplied",
        [{"evidence_head_sha": "a" * 40}, {"current_head_sha": "a" * 40}],
        ids=["evidence-only", "current-only"],
    )
    def test_half_a_pair_blocks(self, supplied: dict[str, str]) -> None:
        verdict, reason = adjudicate(
            ReviewProposal(recommended=ReviewVerdict.APPROVE),
            **_PERMISSIVE,
            **supplied,
        )
        assert verdict is ReviewVerdict.REQUEST_CHANGES
        assert reason is AdjudicationReason.SNAPSHOT_UNKNOWN

    def test_a_matching_pair_still_does_not_block(self) -> None:
        """Non-vacuity: the rule above must be about the PAIR being partial,
        not about the shas being read at all."""
        verdict, _ = adjudicate(
            ReviewProposal(recommended=ReviewVerdict.APPROVE),
            **_PERMISSIVE,
            evidence_head_sha="a" * 40,
            current_head_sha="a" * 40,
        )
        assert verdict is ReviewVerdict.APPROVE


class TestSafetyInputsHaveNoPermissiveDefault:
    """Finding 5. ``hitl_required=False`` and ``reviewer_independent=True``.

    ``admit_dispatch`` states the rule for the same class of input: *a caller
    that forgets either must fail loudly rather than dispatch fail-open.* Given
    finding 1, forgetful wiring is the likely wiring.
    """

    @pytest.mark.parametrize("omitted", ["hitl_required", "reviewer_independent"])
    def test_a_caller_that_forgets_one_gets_a_type_error(self, omitted: str) -> None:
        kwargs = {k: v for k, v in _PERMISSIVE.items() if k != omitted}
        with pytest.raises(TypeError, match=omitted):
            adjudicate(  # type: ignore[arg-type]
                ReviewProposal(recommended=ReviewVerdict.APPROVE), **kwargs
            )


class TestTheReasonCodeMatchesTheVerdict:
    """Finding 6. ``RECOMMENDATION_ACCEPTED`` on a recommendation that lost.

    An ``APPROVE`` carrying an advisory finding came back ``COMMENT`` with
    reason ``RECOMMENDATION_ACCEPTED``. It was not accepted; the binding
    constraint was the advisory-findings floor, and ``FINDINGS_PRESENT``
    already says so. Nothing pinned it — the test discarded the reason.
    """

    def test_an_overridden_recommendation_says_findings_present(self) -> None:
        verdict, reason = adjudicate(
            ReviewProposal(
                recommended=ReviewVerdict.APPROVE,
                findings=(ReviewFinding(summary="nit", blocking=False),),
            ),
            **_PERMISSIVE,
        )
        assert verdict is ReviewVerdict.COMMENT
        assert reason is AdjudicationReason.FINDINGS_PRESENT

    def test_an_honoured_recommendation_still_says_accepted(self) -> None:
        """Non-vacuity: reporting FINDINGS_PRESENT whenever findings exist
        would satisfy the test above and be just as dishonest."""
        _, reason = adjudicate(
            ReviewProposal(
                recommended=ReviewVerdict.COMMENT,
                findings=(ReviewFinding(summary="nit", blocking=False),),
            ),
            **_PERMISSIVE,
        )
        assert reason is AdjudicationReason.RECOMMENDATION_ACCEPTED


class TestTheSecretScrubCoversWhatPydanticAccepts:
    """Finding 7. The scrub ran on ``str``/``list``/``tuple`` only.

    Pydantic's lax mode accepts ``set``/``frozenset``/``deque``/generators for
    a sequence field and ``bytes`` for a ``str`` field, and every one of those
    reached the model unscrubbed. Two are realistic: a deduplicated changed-file
    list is a ``set``, and a diff read off an un-texted subprocess pipe is
    ``bytes``. Both were confirmed to leak a live token by execution.

    The fix is normalisation, not a longer ``isinstance`` tuple — the tuple is
    the same defect one type later.
    """

    SECRET = "hfgwctl_" + "c" * 40

    @pytest.mark.parametrize(
        ("field", "container"),
        [
            ("test_failures", set),
            ("changed_files", frozenset),
            ("changed_files", deque),
            ("changed_files", list),
            ("changed_files", tuple),
        ],
        ids=["set", "frozenset", "deque", "list", "tuple"],
    )
    def test_a_secret_inside_any_sequence_shape_is_scrubbed(
        self, field: str, container: type
    ) -> None:
        payload = build_review_evidence(
            {"issue_number": 1, field: container([f"tok {self.SECRET}"])}
        ).as_payload()
        assert self.SECRET not in repr(payload)

    def test_a_secret_in_a_generator_is_scrubbed(self) -> None:
        payload = build_review_evidence(
            {"issue_number": 1, "changed_files": (f"tok {self.SECRET}" for _ in "x")}
        ).as_payload()
        assert self.SECRET not in repr(payload)

    def test_a_secret_in_a_bytes_diff_is_scrubbed(self) -> None:
        payload = build_review_evidence(
            {"issue_number": 1, "diff": f"+TOKEN={self.SECRET}\n".encode()}
        ).as_payload()
        assert self.SECRET not in repr(payload)

    def test_the_normaliser_widens_nothing(self) -> None:
        """A ``Mapping`` walked into a tuple of its keys would make evidence
        ACCEPT a shape it refuses today. A scrub that quietly admits a new
        shape is a widening wearing a safety label."""
        with pytest.raises(ValidationError):
            build_review_evidence({"issue_number": 1, "changed_files": {"a": 1}})


class TestTheScrubWalkTerminates:
    """The defect the scrub FIX introduced, found reviewing the fix (#11543).

    Widening the walk from ``list``/``tuple`` to any ``Iterable`` closed the
    leak and opened two ways to not terminate that the narrower version could
    not have had: a ``list`` is always finite, and the old code never recursed.
    So an endless generator walked forever and a deeply nested structure hit
    ``RecursionError`` — in a function whose module docstring calls it *pure,
    no I/O, testable against a value*. A pure function that hangs is not one.

    Both ceilings **raise**. Truncating would be the worse bug: a silently
    shortened diff or changed-file list is a reviewer judging something other
    than the change, which is the one failure this module exists to prevent.
    """

    def test_an_endless_iterable_is_refused_rather_than_walked_forever(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            build_review_evidence(
                {"issue_number": 1, "changed_files": itertools.repeat("x")}
            )

    def test_a_deeply_nested_structure_is_refused_rather_than_overflowing(self) -> None:
        nested: object = "x"
        for _ in range(2000):
            nested = [nested]
        with pytest.raises(ValueError, match="nests deeper"):
            build_review_evidence({"issue_number": 1, "changed_files": nested})

    def test_a_realistically_large_bundle_is_untouched(self) -> None:
        """Non-vacuity in the direction that matters: the ceilings must sit far
        above any honest bundle, or the fix trades a hang for a false refusal.

        Five thousand changed files is a monstrous PR and nowhere near the cap.
        """
        payload = build_review_evidence(
            {"issue_number": 1, "changed_files": [f"src/f{i}.py" for i in range(5000)]}
        ).as_payload()
        assert len(payload["changed_files"]) == 5000

    def test_the_bound_did_not_cost_the_scrub(self) -> None:
        """The ceilings must not have been bought by narrowing the walk back."""
        secret = "hfgwctl_" + "e" * 40
        payload = build_review_evidence(
            {
                "issue_number": 1,
                "test_failures": {f"tok {secret}"},
                "diff": f"+T={secret}\n".encode(),
            }
        ).as_payload()
        assert secret not in repr(payload)


class TestTheAllowListGuardsWhatIsRENDERED:
    """Pass 3's finding: the guard asserted a PROXY for its subject.

    ``as_payload`` compared ``model_fields`` and its docstring claimed it
    guarded what got rendered. Those are different sets — ``model_dump()``'s
    keys are a superset — so two subclass shapes walked past it and put
    ``implementer_transcript`` into a reviewer's prompt with every test green.

    That is the defect class this whole file exists to repair, landing one
    layer inside the repair itself: a guard whose stated subject is not the
    thing it checks.
    """

    def test_a_computed_field_cannot_ride_into_the_payload(self) -> None:
        class ViaComputed(ReviewEvidence):
            @computed_field  # type: ignore[prop-decorator]
            @property
            def implementer_transcript(self) -> str:
                return "I considered three approaches and picked..."

        with pytest.raises(ValueError, match="canonical field set"):
            ViaComputed(issue_number=1).as_payload()

    def test_an_extra_allowing_subclass_cannot_smuggle_a_key(self) -> None:
        class ViaExtra(ReviewEvidence):
            model_config = ConfigDict(extra="allow", frozen=True)

        with pytest.raises(ValueError, match="canonical field set"):
            ViaExtra(issue_number=1, implementer_transcript="smuggled").as_payload()

    def test_a_subclass_cannot_hide_a_canonical_field_from_the_reviewer(self) -> None:
        """The other half of ``!=``, and the more dangerous direction.

        Every other test here is an *adds* test, so weakening the guard to
        ``if rendered - CANONICAL_FIELDS:`` — the natural simplification once a
        reader notices that — left the whole suite green, with ``missing``
        computed on a path nothing reached.

        Adds shows a reviewer something extra. **Drops hides the change from
        the reviewer**: excluding ``diff`` renders a review of a change with no
        change in it. Reachable with an ordinary field override, no serializer
        trickery. Matching on ``drops ['diff']`` rather than the generic
        message is what makes this kill that mutation.
        """

        class ViaExcluded(ReviewEvidence):
            diff: str = Field(default="", exclude=True)

        with pytest.raises(ValueError, match=r"drops \['diff'\]"):
            ViaExcluded(issue_number=1).as_payload()

    def test_the_ordinary_payload_still_renders(self) -> None:
        """Non-vacuity: the guard must not refuse the thing it exists to pass."""
        payload = ReviewEvidence(issue_number=1).as_payload()
        assert set(payload) == CANONICAL_FIELDS


class TestOneVocabularyForOneLineage:
    """Both halves of the fence normalise the value the same way.

    The presence test stripped and the membership test did not, so a padded
    lineage counted as *stated* and then failed to match the spawn it names —
    two readings of one value inside one rule.
    """

    def test_a_padded_lineage_still_matches_the_spawn_it_names(self) -> None:
        assert (
            reviewer_independence_refusal(
                role=WorkerRole.REVIEWER,
                requesting_spawn_id="  spawn-impl-1  ",
                implementer_spawn_ids=["spawn-impl-1"],
            )
            is RejectionReason.SELF_REVIEW_FORBIDDEN
        )

    def test_admit_dispatch_reads_it_the_same_way(self) -> None:
        """The SECOND table over the same vocabulary, pinned separately.

        ``reviewer_independence_refusal`` and ``admit_dispatch`` are two
        descriptions of one rule, and a mutation that unstripped only the
        second stayed green against the test above — the exact "two tables,
        one vocabulary" trap. Each table needs its own subject.
        """
        now = datetime.now(UTC)
        lease = DriverLease(
            driver_id="drv-1",
            epoch=0,
            repo_slug="acme/widget",
            issue_number=1,
            phase=DriverPhase.REVIEW,
            expected_stage_label="hydraflow-review",
            phase_attempt=0,
            expires_at=now + timedelta(hours=1),
        )
        request = WorkerDispatchRequest(
            request_id="req-1",
            driver_id="drv-1",
            epoch=0,
            phase_attempt=0,
            worker_role=WorkerRole.REVIEWER,
            model_requirement=ModelRequirement(
                kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-opus"
            ),
            task_contract="review the change",
            reason="the change needs review",
            expected_route_policy_revision="rev-7",
            idempotency_key="key-1",
            requesting_spawn_id="  spawn-impl-1  ",
        )

        reason = admit_dispatch(
            request=request,
            lease=lease,
            now=now,
            route_policy_revision="rev-7",
            live_stage_label="hydraflow-review",
            writer_lease=WriterLease(
                driver_id="drv-1",
                epoch=0,
                worktree_base_digest="b",
                worktree_head_digest="h",
            ),
            sandbox_verified=True,
            allowed_roles=frozenset({WorkerRole.REVIEWER}),
            remaining_usd_budget=10.0,
            implementer_spawn_ids=frozenset({"spawn-impl-1"}),
        )

        assert reason is RejectionReason.SELF_REVIEW_FORBIDDEN
