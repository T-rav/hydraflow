"""Unit tests for the issue-driver control law (ADR-0137, #11535)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from driver_contracts import DriverPhase, RejectionReason
from issue_driver_policy import (
    AdmissionVerdict,
    SchedulingView,
    SlotOccupancy,
    admit_driver,
    admit_phase_result,
    boundary_idempotency_key,
    counts_against_wip,
    is_preemptible,
    phase_for_state,
    rank_candidates,
    select_admissions,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _view(**overrides: object) -> SchedulingView:
    base: dict[str, object] = {
        "issue_number": 1,
        "priority": "P1",
        "driver_state": "READY",
        "stage": "hydraflow-ready",
        "waiting_since": NOW,
    }
    base.update(overrides)
    return SchedulingView(**base)  # type: ignore[arg-type]


def _phase_result(**overrides: object) -> RejectionReason | None:
    kwargs: dict[str, object] = {
        "result_epoch": 3,
        "result_phase_attempt": 1,
        "lease_epoch": 3,
        "lease_phase_attempt": 1,
        "live_stage_label": "hydraflow-plan",
        "accepted_stage_labels": frozenset({"hydraflow-plan"}),
        "idempotency_key": "boundary-1",
    }
    kwargs.update(overrides)
    return admit_phase_result(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# counts_against_wip
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "driver_state",
    [
        # ADR-0137 C6: waiting on a human is not working.
        "PARKED",
        "HITL_WAIT",
        # Retired drivers hold nothing.
        "MERGED",
        "CLOSED",
        "ESCALATED",
    ],
)
def test_a_non_working_driver_state_releases_its_wip_slot(driver_state: str) -> None:
    assert counts_against_wip(driver_state) is False


@pytest.mark.parametrize(
    "driver_state",
    [
        "READY",
        # REVIEW stands for a driver blocked on a congested stage semaphore:
        # it is working, merely queued, so it still counts.
        "REVIEW",
        "PLAN",
    ],
)
def test_a_working_driver_state_counts_against_wip(driver_state: str) -> None:
    assert counts_against_wip(driver_state) is True


# --------------------------------------------------------------------------
# phase_for_state
# --------------------------------------------------------------------------


def test_ready_state_maps_to_the_implement_phase() -> None:
    assert phase_for_state("READY") is DriverPhase.IMPLEMENT


def test_diagnose_state_maps_to_the_review_phase() -> None:
    assert phase_for_state("DIAGNOSE") is DriverPhase.REVIEW


def test_hitl_apply_state_maps_to_the_hitl_phase() -> None:
    assert phase_for_state("HITL_APPLY") is DriverPhase.HITL


def test_merged_state_has_no_phase() -> None:
    assert phase_for_state("MERGED") is None


# --------------------------------------------------------------------------
# is_preemptible
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("driver_state", "at_phase_boundary", "expected"),
    [
        # ADR-0137 C3: mid-subprocess preemption is never legal.
        ("READY", False, False),
        ("READY", True, True),
        # A retired driver has no slot to yield.
        ("MERGED", True, False),
    ],
)
def test_preemption_is_legal_only_at_a_boundary_and_only_while_working(
    driver_state: str, at_phase_boundary: bool, expected: bool
) -> None:
    assert is_preemptible(driver_state, at_phase_boundary=at_phase_boundary) is expected


# --------------------------------------------------------------------------
# SlotOccupancy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("max_in_flight", "in_flight", "expected"),
    [(3, 2, True), (3, 3, False), (1, 2, False)],
)
def test_global_room_exists_only_below_the_cap(
    max_in_flight: int, in_flight: int, expected: bool
) -> None:
    occupancy = SlotOccupancy(max_in_flight=max_in_flight, in_flight=in_flight)

    assert occupancy.has_global_room() is expected


def test_has_stage_room_true_when_the_phase_has_no_declared_cap() -> None:
    occupancy = SlotOccupancy(max_in_flight=5)

    assert occupancy.has_stage_room(DriverPhase.PLAN) is True


def test_has_stage_room_false_when_the_phase_is_at_its_declared_cap() -> None:
    occupancy = SlotOccupancy(
        max_in_flight=5,
        per_stage={DriverPhase.PLAN: 1},
        stage_caps={DriverPhase.PLAN: 1},
    )

    assert occupancy.has_stage_room(DriverPhase.PLAN) is False


def test_with_admitted_increments_the_global_in_flight_count() -> None:
    occupancy = SlotOccupancy(max_in_flight=5, in_flight=1)

    assert occupancy.with_admitted(DriverPhase.PLAN).in_flight == 2


def test_with_admitted_increments_the_named_phase_count() -> None:
    occupancy = SlotOccupancy(
        max_in_flight=5, in_flight=1, per_stage={DriverPhase.PLAN: 1}
    )

    assert occupancy.with_admitted(DriverPhase.PLAN).per_stage[DriverPhase.PLAN] == 2


def test_with_admitted_leaves_the_original_occupancy_untouched() -> None:
    occupancy = SlotOccupancy(max_in_flight=5, in_flight=1)
    occupancy.with_admitted(DriverPhase.PLAN)

    assert occupancy.in_flight == 1


# --------------------------------------------------------------------------
# SchedulingView.band_rank
# --------------------------------------------------------------------------


def test_band_rank_sorts_p0_before_p1() -> None:
    assert _view(priority="P0").band_rank < _view(priority="P1").band_rank


def test_band_rank_sorts_an_absent_band_last() -> None:
    assert _view(priority="none").band_rank > _view(priority="P2").band_rank


# --------------------------------------------------------------------------
# rank_candidates
# --------------------------------------------------------------------------


def test_rank_candidates_puts_p0_first_regardless_of_how_long_it_has_waited() -> None:
    p0 = _view(issue_number=1, priority="P0", waiting_since=NOW)
    long_waiting_p1 = _view(
        issue_number=2, priority="P1", waiting_since=NOW - timedelta(days=10)
    )

    ranked = rank_candidates([long_waiting_p1, p0])

    assert ranked[0].issue_number == 1


def test_rank_candidates_orders_equal_band_candidates_by_longest_wait_first() -> None:
    newer = _view(issue_number=1, priority="P1", waiting_since=NOW)
    older = _view(issue_number=2, priority="P1", waiting_since=NOW - timedelta(hours=5))

    ranked = rank_candidates([newer, older])

    assert ranked[0].issue_number == 2


def test_rank_candidates_breaks_an_exact_wait_tie_by_issue_number() -> None:
    high = _view(issue_number=9, priority="P1", waiting_since=NOW)
    low = _view(issue_number=2, priority="P1", waiting_since=NOW)

    ranked = rank_candidates([high, low])

    assert ranked[0].issue_number == 2


# --------------------------------------------------------------------------
# admit_driver
# --------------------------------------------------------------------------


def test_admit_driver_returns_stop_fenced_when_stop_is_requested() -> None:
    verdict = admit_driver(
        _view(), occupancy=SlotOccupancy(max_in_flight=5), stop_requested=True
    )

    assert verdict is AdmissionVerdict.STOP_FENCED


def test_stop_fenced_takes_priority_over_a_full_global_queue() -> None:
    full_occupancy = SlotOccupancy(max_in_flight=1, in_flight=1)

    verdict = admit_driver(_view(), occupancy=full_occupancy, stop_requested=True)

    assert verdict is AdmissionVerdict.STOP_FENCED


def test_admit_driver_returns_draining_when_draining_is_requested() -> None:
    verdict = admit_driver(
        _view(), occupancy=SlotOccupancy(max_in_flight=5), draining=True
    )

    assert verdict is AdmissionVerdict.DRAINING


def test_admit_driver_returns_already_driven_for_an_issue_a_driver_already_holds() -> (
    None
):
    verdict = admit_driver(
        _view(issue_number=42),
        occupancy=SlotOccupancy(max_in_flight=5),
        driven_issues=frozenset({42}),
    )

    assert verdict is AdmissionVerdict.ALREADY_DRIVEN


def test_admit_driver_returns_terminal_for_a_terminal_driver_state() -> None:
    verdict = admit_driver(
        _view(driver_state="MERGED"), occupancy=SlotOccupancy(max_in_flight=5)
    )

    assert verdict is AdmissionVerdict.TERMINAL


def test_admit_driver_returns_global_wip_full_at_the_cap() -> None:
    verdict = admit_driver(
        _view(), occupancy=SlotOccupancy(max_in_flight=1, in_flight=1)
    )

    assert verdict is AdmissionVerdict.GLOBAL_WIP_FULL


def test_admit_driver_returns_stage_wip_full_when_the_phase_is_at_its_cap() -> None:
    occupancy = SlotOccupancy(
        max_in_flight=5,
        per_stage={DriverPhase.IMPLEMENT: 1},
        stage_caps={DriverPhase.IMPLEMENT: 1},
    )

    verdict = admit_driver(_view(driver_state="READY"), occupancy=occupancy)

    assert verdict is AdmissionVerdict.STAGE_WIP_FULL


def test_admit_driver_admits_on_the_happy_path() -> None:
    verdict = admit_driver(_view(), occupancy=SlotOccupancy(max_in_flight=5))

    assert verdict is AdmissionVerdict.ADMIT


# --------------------------------------------------------------------------
# select_admissions
# --------------------------------------------------------------------------


def test_select_admissions_returns_empty_when_stop_is_requested() -> None:
    admitted = select_admissions(
        [_view(issue_number=1)],
        occupancy=SlotOccupancy(max_in_flight=5),
        stop_requested=True,
    )

    assert admitted == ()


def test_select_admissions_returns_empty_when_draining() -> None:
    admitted = select_admissions(
        [_view(issue_number=1)],
        occupancy=SlotOccupancy(max_in_flight=5),
        draining=True,
    )

    assert admitted == ()


def test_select_admissions_takes_only_as_many_as_the_global_cap_allows() -> None:
    views = [
        _view(issue_number=i, waiting_since=NOW - timedelta(hours=i)) for i in range(5)
    ]

    admitted = select_admissions(views, occupancy=SlotOccupancy(max_in_flight=2))

    assert len(admitted) == 2


def test_a_saturated_stage_does_not_block_a_lower_ranked_candidate_in_a_different_phase() -> (
    None
):
    # IMPLEMENT is fully saturated, so the top-ranked candidate for it is
    # skipped rather than stalling the whole batch; the PLAN candidate behind
    # it still gets the one remaining global slot.
    saturated_stage_candidate = _view(
        issue_number=1, priority="P0", driver_state="READY", waiting_since=NOW
    )
    different_phase_candidate = _view(
        issue_number=2,
        priority="P1",
        driver_state="PLAN",
        waiting_since=NOW - timedelta(hours=1),
    )
    occupancy = SlotOccupancy(max_in_flight=1, stage_caps={DriverPhase.IMPLEMENT: 0})

    admitted = select_admissions(
        [different_phase_candidate, saturated_stage_candidate], occupancy=occupancy
    )

    assert [v.issue_number for v in admitted] == [2]


def test_select_admissions_never_admits_the_same_issue_twice_in_one_batch() -> None:
    duplicate_a = _view(issue_number=7, waiting_since=NOW)
    duplicate_b = _view(issue_number=7, waiting_since=NOW - timedelta(hours=1))

    admitted = select_admissions(
        [duplicate_a, duplicate_b], occupancy=SlotOccupancy(max_in_flight=5)
    )

    assert len(admitted) == 1


# --------------------------------------------------------------------------
# admit_phase_result
# --------------------------------------------------------------------------


def test_admit_phase_result_admits_on_the_happy_path() -> None:
    assert _phase_result() is None


def test_admit_phase_result_stop_fence_wins_over_every_other_rejection_reason() -> None:
    reason = _phase_result(stop_requested=True, result_epoch=99)

    assert reason is RejectionReason.STOP_FENCE


def test_admit_phase_result_rejects_a_result_from_a_stale_epoch() -> None:
    reason = _phase_result(result_epoch=2)

    assert reason is RejectionReason.STALE_EPOCH


def test_admit_phase_result_rejects_a_result_from_a_stale_phase_attempt() -> None:
    reason = _phase_result(result_phase_attempt=0)

    assert reason is RejectionReason.STALE_PHASE_ATTEMPT


def test_admit_phase_result_rejects_when_the_live_label_is_outside_the_accepted_set() -> (
    None
):
    reason = _phase_result(live_stage_label="hydraflow-hitl")

    assert reason is RejectionReason.LIVE_LABEL_CHANGED


def test_admit_phase_result_admits_when_the_phase_committed_its_own_transition() -> (
    None
):
    # The live label moved to the *other* accepted member — the phase's own
    # worker committed it, so this is not external interference.
    reason = _phase_result(
        live_stage_label="hydraflow-ready",
        accepted_stage_labels=frozenset({"hydraflow-plan", "hydraflow-ready"}),
    )

    assert reason is None


def test_admit_phase_result_rejects_an_already_committed_idempotency_key() -> None:
    reason = _phase_result(
        idempotency_key="boundary-1",
        committed_idempotency_keys=frozenset({"boundary-1"}),
    )

    assert reason is RejectionReason.DUPLICATE_IDEMPOTENCY_KEY


def test_admit_phase_result_prefers_stale_epoch_over_live_label_changed_when_both_hold() -> (
    None
):
    reason = _phase_result(result_epoch=2, live_stage_label="hydraflow-hitl")

    assert reason is RejectionReason.STALE_EPOCH


# --------------------------------------------------------------------------
# boundary_idempotency_key
# --------------------------------------------------------------------------


def test_boundary_idempotency_key_is_the_same_for_the_same_tokens() -> None:
    key_a = boundary_idempotency_key(
        issue_number=42, epoch=3, phase=DriverPhase.PLAN, phase_attempt=1
    )
    key_b = boundary_idempotency_key(
        issue_number=42, epoch=3, phase=DriverPhase.PLAN, phase_attempt=1
    )

    assert key_a == key_b


def test_boundary_idempotency_key_differs_for_a_different_epoch() -> None:
    key_a = boundary_idempotency_key(
        issue_number=42, epoch=3, phase=DriverPhase.PLAN, phase_attempt=1
    )
    key_b = boundary_idempotency_key(
        issue_number=42, epoch=4, phase=DriverPhase.PLAN, phase_attempt=1
    )

    assert key_a != key_b


def test_boundary_idempotency_key_differs_for_a_different_phase_attempt() -> None:
    key_a = boundary_idempotency_key(
        issue_number=42, epoch=3, phase=DriverPhase.PLAN, phase_attempt=1
    )
    key_b = boundary_idempotency_key(
        issue_number=42, epoch=3, phase=DriverPhase.PLAN, phase_attempt=2
    )

    assert key_a != key_b
