"""Regression (#9841): LoopFitness scorecards were permanently insufficient_data.

`fitness_min_samples` defaulted to 20 while the scored proposer loops filed
6-14 labeled PRs per 30-day window (live fitness.jsonl: term_proposer topped
out at 6 samples, edge_proposer at 14) — the floor was unreachable at real
cadences, so every scorecard row said insufficient_data forever and
docs/arch/generated/loop-fitness.md never showed a single real score. Two
loops (HumanSteeringLoop, DisturbanceDampenerLoop) additionally ignored the
config knob entirely, using the hardcoded function default.

Pins:
- the production default is right-sized to observed proposer throughput;
- a scored loop at production defaults produces a REAL score from the live
  observed sample volume (14 filed / 30 days) and from a daily cadence run
  for one week (7 filed / 7 days);
- `cadence_min_samples` caps the requirement at the loop's achievable tick
  count so no cadence/window combination can be mathematically unreachable.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from loop_fitness import (
    Confidence,
    FitnessContext,
    IssueRecord,
    cadence_min_samples,
    proposal_acceptance_fitness,
)

_END = datetime(2026, 7, 20, tzinfo=UTC)
_DAY = 86400


def _window_ctx(days: int, *, label: str, filed: int, accepted: int) -> FitnessContext:
    return FitnessContext(
        window_start=_END - timedelta(days=days),
        window_end=_END,
        issues=[
            IssueRecord(
                number=i,
                labels=[label],
                is_pr=True,
                merged=(i < accepted),
                created_at=_END - timedelta(days=1),
            )
            for i in range(filed)
        ],
    )


def test_default_min_samples_is_reachable_at_observed_proposer_throughput() -> None:
    from config import HydraFlowConfig

    default = HydraFlowConfig.model_fields["fitness_min_samples"].default
    # Live 30-day throughput when #9841 was filed: edge_proposer=14,
    # term_proposer=6. The default floor must sit at or below what the
    # busier proposer actually files, or no loop ever scores.
    assert default <= 6, (
        f"fitness_min_samples default {default} is above the observed per-window "
        "sample volume of the scored proposer loops (6-14 per 30 days) — this "
        "re-creates the permanent insufficient_data state of #9841"
    )


def test_live_observed_volume_produces_real_score_at_defaults() -> None:
    from config import HydraFlowConfig

    default = HydraFlowConfig.model_fields["fitness_min_samples"].default
    # Exactly the stuck live shape: 14 filed / 4 accepted in a 30-day window
    # (edge_proposer), daily cadence.
    ctx = _window_ctx(30, label="edge-proposal", filed=14, accepted=4)
    fit = proposal_acceptance_fitness(
        ctx,
        worker_name="edge_proposer",
        label="edge-proposal",
        min_samples=cadence_min_samples(
            ctx, interval_seconds=_DAY, configured_min=default
        ),
    )
    assert fit.confidence is Confidence.OK
    assert fit.score == 4 / 14


def test_daily_cadence_week_of_samples_produces_real_score_at_defaults() -> None:
    from config import HydraFlowConfig

    default = HydraFlowConfig.model_fields["fitness_min_samples"].default
    ctx = _window_ctx(7, label="edge-proposal", filed=7, accepted=4)
    fit = proposal_acceptance_fitness(
        ctx,
        worker_name="edge_proposer",
        label="edge-proposal",
        min_samples=cadence_min_samples(
            ctx, interval_seconds=_DAY, configured_min=default
        ),
    )
    assert fit.confidence is Confidence.OK
    assert fit.score == 4 / 7


def test_no_cadence_window_combination_is_mathematically_unreachable() -> None:
    # For any interval, the derived requirement never exceeds the number of
    # ticks the loop can run inside the window (once achievable >= floor).
    ctx = _window_ctx(30, label="x", filed=0, accepted=0)
    window_seconds = 30 * _DAY
    for interval in (60, 3600, 14400, _DAY, 7 * _DAY):
        achievable = window_seconds // interval
        derived = cadence_min_samples(ctx, interval_seconds=interval, configured_min=20)
        assert derived <= max(3, achievable)
