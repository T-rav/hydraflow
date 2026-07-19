from __future__ import annotations

from tests.helpers import ConfigFactory


def test_fitness_defaults() -> None:
    config = ConfigFactory.create()
    assert config.fitness_scorecard_interval == 86400
    assert config.fitness_window_days == 30
    assert config.fitness_min_samples == 20


def test_fitness_interval_env_override(monkeypatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_FITNESS_SCORECARD_INTERVAL", "3600")
    config = ConfigFactory.create()
    assert config.fitness_scorecard_interval == 3600
