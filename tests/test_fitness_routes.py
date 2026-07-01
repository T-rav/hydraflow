from __future__ import annotations

from datetime import UTC, datetime

from fitness_report import save_fitness_snapshots
from loop_fitness import Confidence, FitnessKind, LoopFitness
from tests.helpers import ConfigFactory


def test_latest_fitness_per_worker(tmp_path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    old = LoopFitness(
        worker_name="alpha",
        kind=FitnessKind.SCORED,
        score=0.1,
        sample_count=5,
        confidence=Confidence.OK,
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
    )
    new = LoopFitness(
        worker_name="alpha",
        kind=FitnessKind.SCORED,
        score=0.9,
        sample_count=9,
        confidence=Confidence.OK,
        timestamp=datetime(2026, 6, 30, tzinfo=UTC),
    )
    save_fitness_snapshots(config, [old])
    save_fitness_snapshots(config, [new])

    from dashboard_routes._fitness_routes import latest_fitness_by_worker

    latest = latest_fitness_by_worker(config)
    assert latest["alpha"]["score"] == 0.9  # newest wins
