"""MockWorld scenario for the FitnessScorecardLoop producer.

Runs the producer against a seeded fleet of two loops with crafted issue
history.  Asserts it emits ``LOOP_FITNESS_UPDATE`` and writes
``fitness.jsonl`` with the expected per-loop records.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from base_background_loop import BaseBackgroundLoop
from fitness_scorecard_loop import FitnessScorecardLoop
from loop_fitness import (
    FitnessContext,
    FitnessKind,
    IssueRecord,
    LoopFitness,
)
from tests.helpers import make_bg_loop_deps

pytestmark = pytest.mark.scenario_loops


class _Proposer(BaseBackgroundLoop):
    def _get_default_interval(self) -> int:
        return 60

    async def _do_work(self):
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        return {}

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        from loop_fitness import proposal_acceptance_fitness

        return proposal_acceptance_fitness(
            ctx, worker_name=self._worker_name, label="x-proposal", min_samples=1
        )


@pytest.mark.asyncio
async def test_scorecard_scenario(tmp_path) -> None:
    d = make_bg_loop_deps(tmp_path, fitness_window_days=30)
    d.bus.load_events_since = AsyncMock(return_value=[])

    async def fetch() -> list[IssueRecord]:
        return [
            IssueRecord(
                number=n,
                labels=["x-proposal"],
                is_pr=True,
                merged=(n % 2 == 0),
                created_at=datetime(2026, 6, 15, tzinfo=UTC),
            )
            for n in range(4)
        ]

    producer = FitnessScorecardLoop(
        config=d.config, deps=d.loop_deps, issue_fetcher=fetch, repo_root=tmp_path
    )
    proposer = _Proposer(worker_name="x_proposer", config=d.config, deps=d.loop_deps)
    producer.set_loops({"x_proposer": proposer, "fitness_scorecard": producer})

    payload = await producer._do_work()

    assert payload["loop_count"] == 2
    assert payload["scored_count"] == 1
    rows = [
        json.loads(line)
        for line in (d.config.repo_data_root / "metrics" / "fitness.jsonl")
        .read_text()
        .splitlines()
    ]
    by_name = {r["worker_name"]: r for r in rows}
    assert by_name["x_proposer"]["kind"] == FitnessKind.SCORED.value
    assert by_name["x_proposer"]["score"] == 0.5  # 2 of 4 merged
    assert by_name["fitness_scorecard"]["kind"] == FitnessKind.HOUSEKEEPING.value
