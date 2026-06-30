from __future__ import annotations

import json
from datetime import UTC, datetime

from fitness_report import render_fitness_markdown, save_fitness_snapshots
from loop_fitness import Confidence, FitnessKind, LoopFitness
from tests.helpers import ConfigFactory

_TS = datetime(2026, 6, 30, tzinfo=UTC)


def _scored(name: str, score: float) -> LoopFitness:
    return LoopFitness(
        worker_name=name,
        kind=FitnessKind.SCORED,
        score=score,
        components={"filed": 10.0, "accepted": score * 10},
        sample_count=10,
        confidence=Confidence.OK,
        timestamp=_TS,
    )


def _housekeeping(name: str) -> LoopFitness:
    return LoopFitness(
        worker_name=name,
        kind=FitnessKind.HOUSEKEEPING,
        timestamp=_TS,
    )


def test_render_sorts_by_name_not_score() -> None:
    md = render_fitness_markdown([_scored("zeta", 0.9), _scored("alpha", 0.1)])
    assert md.index("alpha") < md.index("zeta")  # alphabetical, not by score
    assert "0.10" in md and "0.90" in md


def test_render_shows_na_for_housekeeping() -> None:
    md = render_fitness_markdown([_housekeeping("diagram_loop")])
    assert "diagram_loop" in md
    assert "n/a" in md.lower()


def test_save_appends_jsonl(tmp_path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    path = save_fitness_snapshots(config, [_scored("term_proposer", 0.5)])
    assert path.name == "fitness.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["worker_name"] == "term_proposer"
    assert rows[0]["score"] == 0.5
