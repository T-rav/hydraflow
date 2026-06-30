from __future__ import annotations

from datetime import UTC, datetime

from loop_fitness import (
    Confidence,
    FitnessContext,
    FitnessKind,
    IssueRecord,
    proposal_acceptance_fitness,
)

_START = datetime(2026, 6, 1, tzinfo=UTC)
_END = datetime(2026, 6, 30, tzinfo=UTC)


def _ctx(issues: list[IssueRecord]) -> FitnessContext:
    return FitnessContext(window_start=_START, window_end=_END, issues=issues)


def _pr(number: int, *, merged: bool) -> IssueRecord:
    return IssueRecord(
        number=number,
        labels=["term-proposal"],
        is_pr=True,
        state="closed" if merged else "open",
        merged=merged,
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
    )


def test_scores_acceptance_rate_when_enough_samples() -> None:
    issues = [_pr(i, merged=i < 6) for i in range(10)]  # 6 of 10 merged
    fit = proposal_acceptance_fitness(
        _ctx(issues), worker_name="term_proposer", label="term-proposal", min_samples=5
    )
    assert fit.kind is FitnessKind.SCORED
    assert fit.confidence is Confidence.OK
    assert fit.score == 0.6
    assert fit.components == {"filed": 10.0, "accepted": 6.0}
    assert fit.sample_count == 10
    assert fit.timestamp == _END


def test_insufficient_data_below_min_samples() -> None:
    fit = proposal_acceptance_fitness(
        _ctx([_pr(1, merged=True)]),
        worker_name="term_proposer",
        label="term-proposal",
        min_samples=20,
    )
    assert fit.score is None
    assert fit.confidence is Confidence.INSUFFICIENT_DATA
    assert fit.sample_count == 1


def test_ignores_other_labels_and_out_of_window() -> None:
    other_label = IssueRecord(
        number=99,
        labels=["unrelated"],
        is_pr=True,
        merged=True,
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    out_of_window = IssueRecord(
        number=98,
        labels=["term-proposal"],
        is_pr=True,
        merged=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    fit = proposal_acceptance_fitness(
        _ctx([other_label, out_of_window]),
        worker_name="term_proposer",
        label="term-proposal",
        min_samples=1,
    )
    assert fit.sample_count == 0
    assert fit.score is None  # no filed items in window
