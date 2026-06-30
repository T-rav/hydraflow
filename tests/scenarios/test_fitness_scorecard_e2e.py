"""End-to-end test for the Loop Fitness Scorecard feature.

Exercises the full producer-to-route pipeline with real I/O (no mocks-of-mocks):
  producer tick → fitness.jsonl persisted → loop-fitness.md artifact written
  → latest_fitness_by_worker() route helper returns the latest row per worker.

Convention mirrored: tests/scenarios/test_fitness_scorecard_scenario.py (lines 47-84)
— in-process _do_work() with real EventBus, real config (ConfigFactory.create pointing
at tmp_path), and a fake issue_fetcher.  No docker / live services required.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from base_background_loop import BaseBackgroundLoop
from dashboard_routes._fitness_routes import latest_fitness_by_worker
from events import EventType
from fitness_scorecard_loop import FitnessScorecardLoop
from loop_fitness import (
    FitnessContext,
    FitnessKind,
    IssueRecord,
    LoopFitness,
)
from metrics_manager import get_metrics_cache_dir
from tests.helpers import make_bg_loop_deps

pytestmark = pytest.mark.scenario_loops


class _Proposer(BaseBackgroundLoop):
    """Minimal scored loop — uses proposal_acceptance_fitness for a real score."""

    def _get_default_interval(self) -> int:
        return 60

    async def _do_work(self):
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        return {}

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        from loop_fitness import proposal_acceptance_fitness

        return proposal_acceptance_fitness(
            ctx,
            worker_name=self._worker_name,
            label="x-proposal",
            min_samples=1,
        )


async def test_fitness_scorecard_e2e(tmp_path) -> None:
    """End-to-end: producer tick persists rows, artifact is written, route serves data.

    Asserts:
    1. docs/arch/generated/loop-fitness.md written under tmp_path and contains
       the scored loop's name.
    2. fitness.jsonl exists in metrics cache dir with one row per loop.
    3. latest_fitness_by_worker(config) returns the scored loop's row with
       the expected score — i.e. persisted data flows through to the route.
    4. A LOOP_FITNESS_UPDATE event was published on the real EventBus.
    """
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
        config=d.config,
        deps=d.loop_deps,
        issue_fetcher=fetch,
        repo_root=tmp_path,
    )
    proposer = _Proposer(
        worker_name="x_proposer",
        config=d.config,
        deps=d.loop_deps,
    )
    producer.set_loops({"x_proposer": proposer, "fitness_scorecard": producer})

    payload = await producer._do_work()

    # ── 1. Artifact written and contains the scored loop name ────────────────
    artifact = tmp_path / "docs" / "arch" / "generated" / "loop-fitness.md"
    assert artifact.exists(), f"loop-fitness.md not found at {artifact}"
    content = artifact.read_text()
    assert "x_proposer" in content, f"scored loop name missing from artifact:\n{content}"

    # ── 2. fitness.jsonl has one row per registered loop ─────────────────────
    jsonl_path = get_metrics_cache_dir(d.config) / "fitness.jsonl"
    assert jsonl_path.exists(), f"fitness.jsonl not found at {jsonl_path}"
    rows = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 2, f"expected 2 rows (one per loop), got {len(rows)}: {rows}"
    worker_names = {r["worker_name"] for r in rows}
    assert "x_proposer" in worker_names
    assert "fitness_scorecard" in worker_names

    # ── 3. Route helper returns the latest row per worker, with correct score ─
    # This is the end-to-end link: persisted jsonl → route helper → served data.
    latest = latest_fitness_by_worker(d.config)
    assert "x_proposer" in latest, f"x_proposer missing from route result: {latest}"
    assert latest["x_proposer"]["kind"] == FitnessKind.SCORED.value
    assert latest["x_proposer"]["score"] == pytest.approx(0.5)  # 2 of 4 merged
    assert "fitness_scorecard" in latest
    assert latest["fitness_scorecard"]["kind"] == FitnessKind.HOUSEKEEPING.value

    # ── 4. LOOP_FITNESS_UPDATE published on the real EventBus ────────────────
    history = d.bus.get_history()
    fitness_events = [
        e for e in history if getattr(e, "type", None) == EventType.LOOP_FITNESS_UPDATE
    ]
    assert len(fitness_events) == 1, (
        f"expected 1 LOOP_FITNESS_UPDATE event, got {len(fitness_events)}: "
        f"{[e.type for e in history]}"
    )
    assert fitness_events[0].data["loop_count"] == 2
    assert fitness_events[0].data["scored_count"] == 1

    # Payload returned from _do_work is consistent with what the event carries.
    assert payload["loop_count"] == 2
    assert payload["scored_count"] == 1
