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

from collections import deque

import pytest
from pydantic import ValidationError

from driver_contracts import (
    WORKER_CATALOG,
    DriverPhase,
    RejectionReason,
    WorkerRole,
    WriteScope,
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
from review_evidence import build_review_evidence

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
