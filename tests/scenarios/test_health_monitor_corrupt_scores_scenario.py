"""An unparseable item_scores.json must not escalate to a human.

#6602's unit pins assert the VALUE `compute_trend_metrics` returns. This
drives the real `HealthMonitorLoop` and asserts the consequence: whether a
`[Health Monitor] avg_memory_score ...` recommendation is written to
`hitl_recommendations.jsonl`, which is what a human is eventually asked to
act on.

That is the harm the issue describes and the part a unit test does not
reach. `avg_memory_score` defaulting to 0.0 on a parse failure is below
`_AVG_SCORE_LOW` (0.4), so the loop concluded that "most memory items are
not contributing to positive outcomes" and recommended a full memory
compaction pass — on the strength of a file it could not read.

The healthy-scores case is the decoy: without it, a test asserting only "no
recommendation" would pass just as well against a loop that never
recommends anything.
"""

from __future__ import annotations

import json

import pytest

from tests.helpers import make_bg_loop_deps
from tests.scenarios.catalog.loop_catalog import LoopCatalog
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_AVG_SCORE_TITLE = "[Health Monitor] avg_memory_score"


def _build_loop(world: MockWorld, tmp_path):
    bg = make_bg_loop_deps(tmp_path)
    loop = LoopCatalog.instantiate(
        "health_monitor",
        ports={"github": world.github, "state": world._harness.state},
        config=bg.config,
        deps=bg.loop_deps,
    )
    return loop, bg.config


def _recommendation_titles(config) -> list[str]:
    path = config.data_path("memory", "hitl_recommendations.jsonl")
    if not path.exists():
        return []
    return [
        json.loads(line)["title"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def test_corrupt_scores_file_files_no_memory_recommendation(
    tmp_path,
) -> None:
    """A file the loop cannot parse must produce no score-based escalation."""
    world = MockWorld(tmp_path)
    loop, config = _build_loop(world, tmp_path)

    scores = loop._scores_path
    scores.parent.mkdir(parents=True, exist_ok=True)
    scores.write_text("{ this is not valid json", encoding="utf-8")

    await loop._do_work()

    titles = _recommendation_titles(config)
    assert not [t for t in titles if t.startswith(_AVG_SCORE_TITLE)], (
        "A corrupt item_scores.json escalated a memory-compaction "
        f"recommendation to a human. Recommendations filed: {titles}"
    )


async def test_genuinely_low_scores_still_file_a_recommendation(
    tmp_path,
) -> None:
    """The decoy: real low scores must still escalate.

    Without this, the assertion above would be satisfied by a loop that had
    simply stopped recommending anything — including for the case the
    recommendation exists to catch.
    """
    world = MockWorld(tmp_path)
    loop, config = _build_loop(world, tmp_path)

    scores = loop._scores_path
    scores.parent.mkdir(parents=True, exist_ok=True)
    scores.write_text(
        json.dumps({f"item{i}": {"score": 0.05, "appearances": 9} for i in range(5)}),
        encoding="utf-8",
    )

    await loop._do_work()

    titles = _recommendation_titles(config)
    assert [t for t in titles if t.startswith(_AVG_SCORE_TITLE)], (
        "Genuinely low memory scores should still reach a human — this test "
        f"is what stops the fix above from silencing the signal. Filed: {titles}"
    )
