"""Bounded fallback: the ceiling, the evidence, and what a hop may never reach.

"Bounded" has to survive being read literally, so these tests state the bound
four ways: a hard hop ceiling, a citation that only the gateway's own terminal
evidence can license, a prior lease that must already be released, and a start
position that can only ever move *further down* a candidate list this module
never chooses.
"""

from __future__ import annotations

import pytest

from hydraflow_gateway.models import GatewayRequestStatus
from hydraflow_gateway.routing_fallback import (
    CitedDecision,
    FallbackRefusal,
    TerminalDecisionIndex,
    TerminalEvidence,
    authorise_fallback,
    condition_for_terminal,
    outcome_for,
)
from hydraflow_gateway.routing_policy import DecisionOutcome, FallbackCondition

_DISPATCH = "disp-1"
_REPO = "acme/project-x"
_MODEL = "glm-5.3"


def _cited(**overrides: object) -> CitedDecision:
    payload: dict[str, object] = {
        "selected": True,
        "dispatch_id": _DISPATCH,
        "repo": _REPO,
        "effective_model": _MODEL,
        "account_id": "legacy-zai-harness",
        "fallback_position": 0,
        "fallback_hops": 0,
        "key_id": "key-0",
    }
    payload.update(overrides)
    return CitedDecision(**payload)  # type: ignore[arg-type]


def _qualifying() -> TerminalEvidence:
    return TerminalEvidence(
        account_id="legacy-zai-harness",
        condition=FallbackCondition.RATE_LIMITED,
        recorded_epoch=1.0,
    )


def _authorise(**overrides: object):  # noqa: ANN201 - the verdict type is the subject
    payload: dict[str, object] = {
        "cited": _cited(),
        "evidence": _qualifying(),
        "lease_held": False,
        "dispatch_id": _DISPATCH,
        "repo": _REPO,
        "effective_model": _MODEL,
        "advance": True,
        "max_hops": 1,
    }
    payload.update(overrides)
    return authorise_fallback(**payload)  # type: ignore[arg-type]


# -- classifying the gateway's own terminal rows -----------------------------


@pytest.mark.parametrize(
    ("status_code", "status", "expected"),
    [
        pytest.param(
            429,
            GatewayRequestStatus.UPSTREAM_ERROR,
            FallbackCondition.RATE_LIMITED,
            id="rate-limited",
        ),
        pytest.param(
            402,
            GatewayRequestStatus.UPSTREAM_ERROR,
            FallbackCondition.CREDIT_EXHAUSTED,
            id="credit-exhausted",
        ),
        pytest.param(
            503,
            GatewayRequestStatus.UPSTREAM_ERROR,
            FallbackCondition.UNAVAILABLE,
            id="upstream-unavailable",
        ),
        pytest.param(
            502,
            GatewayRequestStatus.UPSTREAM_ERROR,
            FallbackCondition.UNAVAILABLE,
            id="proxy-could-not-reach-upstream",
        ),
        pytest.param(200, GatewayRequestStatus.COMPLETED, None, id="success"),
        pytest.param(
            400, GatewayRequestStatus.UPSTREAM_ERROR, None, id="caller-sent-a-bad-body"
        ),
        pytest.param(
            403,
            GatewayRequestStatus.UPSTREAM_ERROR,
            None,
            id="forbidden-is-not-guessed-as-credit",
        ),
        pytest.param(
            499, GatewayRequestStatus.CLIENT_ABORTED, None, id="client-hung-up"
        ),
        pytest.param(
            429,
            GatewayRequestStatus.CLIENT_ABORTED,
            None,
            id="client-hung-up-outranks-the-status",
        ),
    ],
)
def test_a_terminal_row_classifies_into_one_qualifying_class(
    status_code: int, status: GatewayRequestStatus, expected: FallbackCondition | None
) -> None:
    assert condition_for_terminal(status_code=status_code, status=status) is expected


# -- the evidence index ------------------------------------------------------


def test_evidence_is_recoverable_by_the_decision_it_belongs_to() -> None:
    index = TerminalDecisionIndex()
    index.record(
        "gwd_1", account_id="a", condition=FallbackCondition.RATE_LIMITED, now=1.0
    )
    evidence = index.get("gwd_1")
    assert evidence is not None and evidence.condition is FallbackCondition.RATE_LIMITED


def test_an_unrecorded_decision_has_no_evidence() -> None:
    assert TerminalDecisionIndex().get("gwd_unknown") is None


def test_a_later_success_replaces_an_earlier_failure() -> None:
    index = TerminalDecisionIndex()
    index.record(
        "gwd_1", account_id="a", condition=FallbackCondition.RATE_LIMITED, now=1.0
    )
    index.record("gwd_1", account_id="a", condition=None, now=2.0)
    evidence = index.get("gwd_1")
    assert evidence is not None and evidence.condition is None


def test_the_evidence_index_evicts_its_oldest_entry_at_the_ceiling() -> None:
    index = TerminalDecisionIndex(max_tracked=2)
    for seq in range(3):
        index.record(f"gwd_{seq}", account_id="a", condition=None, now=float(seq))
    assert (index.tracked, index.get("gwd_0")) == (2, None)


def test_the_evidence_index_refuses_a_ceiling_of_zero() -> None:
    with pytest.raises(ValueError, match="max_tracked"):
        TerminalDecisionIndex(max_tracked=0)


# -- what licenses a hop -----------------------------------------------------


def test_a_qualifying_terminal_outcome_advances_one_position() -> None:
    assert _authorise().start_position == 1


def test_an_advance_counts_against_the_hop_budget() -> None:
    assert _authorise().hops == 1


def test_a_hop_starts_past_the_account_that_failed_not_merely_after_it() -> None:
    assert _authorise(cited=_cited(fallback_position=2), max_hops=4).start_position == 3


@pytest.mark.parametrize(
    ("overrides", "refusal"),
    [
        pytest.param(
            {"cited": None},
            FallbackRefusal.LINEAGE_UNKNOWN,
            id="the-cited-decision-is-not-known-here",
        ),
        pytest.param(
            {"cited": _cited(selected=False)},
            FallbackRefusal.CITED_DECISION_NOT_SELECTED,
            id="the-cited-decision-never-took-a-lease",
        ),
        pytest.param(
            {"dispatch_id": "another-dispatch"},
            FallbackRefusal.LINEAGE_MISMATCH,
            id="a-different-dispatch",
        ),
        pytest.param(
            {"repo": "acme/somewhere-else"},
            FallbackRefusal.LINEAGE_MISMATCH,
            id="a-different-repository",
        ),
        pytest.param(
            {"effective_model": "glm-4.6"},
            FallbackRefusal.LINEAGE_MISMATCH,
            id="a-different-effective-model",
        ),
        pytest.param(
            {"lease_held": True},
            FallbackRefusal.LEASE_STILL_HELD,
            id="the-prior-lease-was-never-given-back",
        ),
        pytest.param(
            {"evidence": None},
            FallbackRefusal.NOT_AUTHORISED,
            id="no-terminal-evidence-at-all",
        ),
        pytest.param(
            {
                "evidence": TerminalEvidence(
                    account_id="a", condition=None, recorded_epoch=1.0
                )
            },
            FallbackRefusal.NOT_AUTHORISED,
            id="the-prior-request-succeeded",
        ),
        pytest.param(
            {"max_hops": 0},
            FallbackRefusal.BUDGET_EXHAUSTED,
            id="the-deployment-permits-no-hop-at-all",
        ),
        pytest.param(
            {"cited": _cited(fallback_hops=1), "max_hops": 1},
            FallbackRefusal.BUDGET_EXHAUSTED,
            id="the-budget-is-already-spent",
        ),
    ],
)
def test_an_unlicensed_citation_is_refused_with_its_own_code(
    overrides: dict[str, object], refusal: FallbackRefusal
) -> None:
    assert _authorise(**overrides).refusal is refusal


def test_an_unlicensed_citation_authorises_nothing() -> None:
    assert _authorise(evidence=None).authorised is False


def test_a_refused_hop_reports_no_position_to_start_from() -> None:
    assert _authorise(max_hops=0).start_position == 0


@pytest.mark.parametrize(
    ("refusal", "outcome"),
    [
        pytest.param(
            FallbackRefusal.LINEAGE_MISMATCH,
            DecisionOutcome.REJECTED,
            id="a-mismatched-citation-is-the-callers-error",
        ),
        pytest.param(
            FallbackRefusal.CITED_DECISION_NOT_SELECTED,
            DecisionOutcome.REJECTED,
            id="citing-a-refusal-is-the-callers-error",
        ),
        pytest.param(
            FallbackRefusal.LINEAGE_UNKNOWN,
            DecisionOutcome.HELD,
            id="an-unknown-citation-may-be-a-restart",
        ),
        pytest.param(
            FallbackRefusal.LEASE_STILL_HELD,
            DecisionOutcome.HELD,
            id="a-lease-not-yet-released-may-be-released",
        ),
        pytest.param(
            FallbackRefusal.NOT_AUTHORISED,
            DecisionOutcome.HELD,
            id="evidence-may-still-arrive",
        ),
        pytest.param(
            FallbackRefusal.BUDGET_EXHAUSTED,
            DecisionOutcome.HELD,
            id="an-exhausted-budget-is-not-a-policy-verdict",
        ),
    ],
)
def test_a_refusal_reports_the_disposition_its_kind_implies(
    refusal: FallbackRefusal, outcome: DecisionOutcome
) -> None:
    assert outcome_for(refusal) is outcome


# -- supersede: a replacement, not a hop -------------------------------------


def test_a_supersede_re_mints_at_the_same_position() -> None:
    verdict = _authorise(
        cited=_cited(fallback_position=1, fallback_hops=1),
        advance=False,
        evidence=None,
        max_hops=1,
    )
    assert verdict.start_position == 1


def test_a_supersede_spends_no_hop_budget() -> None:
    verdict = _authorise(
        cited=_cited(fallback_position=1, fallback_hops=1),
        advance=False,
        evidence=None,
        max_hops=0,
    )
    assert verdict.authorised is True


def test_a_supersede_needs_no_terminal_evidence() -> None:
    assert _authorise(advance=False, evidence=None).authorised is True


def test_a_supersede_still_requires_the_prior_lease_to_be_gone() -> None:
    assert _authorise(advance=False, evidence=None, lease_held=True).refusal is (
        FallbackRefusal.LEASE_STILL_HELD
    )


def test_a_zero_hop_ceiling_still_permits_lost_response_recovery() -> None:
    """``0`` refuses hops, not replacements — the documented distinction.

    A supersede moves nowhere and therefore spends no budget, so a deployment
    that has switched fallback off entirely can still recover a mint whose
    response was lost.
    """
    assert _authorise(advance=False, evidence=None, max_hops=0).authorised is True


def test_a_zero_hop_ceiling_refuses_an_ordinary_hop() -> None:
    assert _authorise(max_hops=0).refusal is FallbackRefusal.BUDGET_EXHAUSTED


def test_a_supersede_of_a_decision_that_did_reach_an_upstream_is_refused() -> None:
    """A supersede recovers a LOST response, and terminal evidence proves it was not.

    Without this, a supersede is an unbounded, evidence-free re-mint that pins
    every successor to a position chosen against a pool state that may be long
    gone — including past an account an operator has since re-enabled.
    """
    assert _authorise(advance=False, evidence=_qualifying()).refusal is (
        FallbackRefusal.RESPONSE_WAS_NOT_LOST
    )


def test_a_supersede_of_a_successful_decision_is_refused_too() -> None:
    """Evidence of ANY terminal outcome proves the caller got its credential."""
    verdict = _authorise(
        advance=False,
        evidence=TerminalEvidence(account_id="a", condition=None, recorded_epoch=1.0),
    )

    assert verdict.refusal is FallbackRefusal.RESPONSE_WAS_NOT_LOST


def test_claiming_a_response_was_lost_when_it_was_not_is_the_callers_error() -> None:
    assert outcome_for(FallbackRefusal.RESPONSE_WAS_NOT_LOST) is (
        DecisionOutcome.REJECTED
    )
