# tests/test_fitness_scorecard_loop.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import BaseBackgroundLoop, LoopDeps
from fitness_scorecard_loop import FitnessScorecardLoop
from loop_fitness import (
    Confidence,
    FitnessContext,
    FitnessKind,
    IssueRecord,
    LoopFitness,
)
from tests.helpers import ConfigFactory


class _ScoredLoop(BaseBackgroundLoop):
    def _get_default_interval(self) -> int:
        return 60

    async def _do_work(self):
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        return {}

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.SCORED,
            score=0.75,
            components={"filed": 4.0},
            sample_count=4,
            confidence=Confidence.OK,
            timestamp=ctx.window_end,
        )


def _deps(bus) -> LoopDeps:
    return LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_producer_scores_loops_and_emits(tmp_path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.load_events_since = AsyncMock(return_value=[])

    async def fetch() -> list[IssueRecord]:
        return [
            IssueRecord(
                number=1,
                labels=["x"],
                is_pr=True,
                merged=True,
                created_at=datetime(2026, 6, 15, tzinfo=UTC),
            )
        ]

    loop = FitnessScorecardLoop(
        config=config, deps=_deps(bus), issue_fetcher=fetch, repo_root=tmp_path
    )
    scored = _ScoredLoop(worker_name="alpha", config=config, deps=_deps(bus))
    loop.set_loops({"alpha": scored, "fitness_scorecard": loop})

    result = await loop._do_work()

    assert result["loop_count"] == 2
    assert result["scored_count"] == 1  # alpha SCORED; producer is HOUSEKEEPING
    bus.publish.assert_awaited_once()
    assert (tmp_path / "docs/arch/generated/loop-fitness.md").exists()
    fitness_jsonl = config.repo_data_root / "metrics" / "fitness.jsonl"
    assert fitness_jsonl.exists()


@pytest.mark.asyncio
async def test_kill_switch_short_circuits(tmp_path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    bus = MagicMock()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=False),
        sleep_fn=AsyncMock(),
    )

    async def fetch() -> list[IssueRecord]:
        return []

    loop = FitnessScorecardLoop(
        config=config, deps=deps, issue_fetcher=fetch, repo_root=tmp_path
    )
    loop.set_loops({})
    assert await loop._do_work() == {"status": "disabled"}


def test_producer_declares_housekeeping_fitness(tmp_path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")

    async def fetch() -> list[IssueRecord]:
        return []

    loop = FitnessScorecardLoop(
        config=config, deps=_deps(MagicMock()), issue_fetcher=fetch
    )
    ctx = FitnessContext(
        window_start=datetime(2026, 6, 1, tzinfo=UTC),
        window_end=datetime(2026, 6, 30, tzinfo=UTC),
    )
    assert loop.loop_fitness(ctx).kind is FitnessKind.HOUSEKEEPING


class _RaisingLoop(BaseBackgroundLoop):
    """Stub loop whose loop_fitness always raises a RuntimeError."""

    def _get_default_interval(self) -> int:
        return 60

    async def _do_work(self):
        return {}

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        raise RuntimeError("boom from loop_fitness")


@pytest.mark.asyncio
async def test_per_loop_isolation_on_loop_fitness_error(tmp_path) -> None:
    """If one loop's loop_fitness raises, the tick must still complete.

    The healthy loop keeps its real row; the raising loop gets a HOUSEKEEPING
    fallback whose notes mention the exception.  The jsonl artifact is written
    and the LOOP_FITNESS_UPDATE event is published.
    """
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.load_events_since = AsyncMock(return_value=[])

    async def fetch() -> list[IssueRecord]:
        return []

    scorecard = FitnessScorecardLoop(
        config=config, deps=_deps(bus), issue_fetcher=fetch, repo_root=tmp_path
    )
    healthy = _ScoredLoop(worker_name="healthy", config=config, deps=_deps(bus))
    raiser = _RaisingLoop(worker_name="raiser", config=config, deps=_deps(bus))
    scorecard.set_loops({"healthy": healthy, "raiser": raiser})

    # (a) _do_work completes without raising
    result = await scorecard._do_work()
    assert result is not None

    # (b) fitness.jsonl and artifact written
    fitness_jsonl = config.repo_data_root / "metrics" / "fitness.jsonl"
    assert fitness_jsonl.exists()
    assert (tmp_path / "docs/arch/generated/loop-fitness.md").exists()

    # (c) LOOP_FITNESS_UPDATE event published
    bus.publish.assert_awaited_once()

    # (d) healthy loop has its real SCORED row; raising loop has HOUSEKEEPING fallback
    import json

    rows = [json.loads(line) for line in fitness_jsonl.read_text().splitlines()]
    by_worker = {r["worker_name"]: r for r in rows}

    assert by_worker["healthy"]["kind"] == FitnessKind.SCORED.value
    raiser_row = by_worker["raiser"]
    assert raiser_row["kind"] == FitnessKind.HOUSEKEEPING.value
    assert raiser_row["score"] is None
    assert "RuntimeError" in (raiser_row.get("notes") or "")
    assert "boom from loop_fitness" in (raiser_row.get("notes") or "")
