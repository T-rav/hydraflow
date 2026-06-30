from __future__ import annotations

from datetime import UTC, datetime

from loop_fitness import (
    Confidence,
    FitnessContext,
    FitnessKind,
    IssueRecord,
    LoopFitness,
)


def test_loop_fitness_json_round_trip() -> None:
    fit = LoopFitness(
        worker_name="term_proposer",
        kind=FitnessKind.SCORED,
        score=0.5,
        components={"filed": 10.0, "accepted": 5.0},
        sample_count=10,
        confidence=Confidence.OK,
        timestamp=datetime(2026, 6, 30, tzinfo=UTC),
    )
    restored = LoopFitness.model_validate_json(fit.model_dump_json())
    assert restored == fit


def test_fitness_context_is_frozen_and_pure_data() -> None:
    ctx = FitnessContext(
        window_start=datetime(2026, 6, 1, tzinfo=UTC),
        window_end=datetime(2026, 6, 30, tzinfo=UTC),
        issues=[
            IssueRecord(
                number=1,
                labels=["term-proposal"],
                is_pr=True,
                state="closed",
                merged=True,
                created_at=datetime(2026, 6, 10, tzinfo=UTC),
            )
        ],
    )
    # Frozen: cannot mutate.
    import pytest
    with pytest.raises(Exception):
        ctx.window_start = datetime(2026, 1, 1, tzinfo=UTC)  # type: ignore[misc]
    # Round-trips as pure data.
    assert FitnessContext.model_validate_json(ctx.model_dump_json()) == ctx
