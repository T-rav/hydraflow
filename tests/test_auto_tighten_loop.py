"""Unit tests for AutoTightenLoop (Task 12 of the auto-tighten ratchet).

Mirrors the construction/async style of tests/test_adr_conformance_loop.py:
a real HydraFlowConfig on tmp_path, a real LoopDeps with an in-memory
EventBus, and fakes/AsyncMocks for the collaborators built in Tasks 2-11
(ObservationStore, CoverageAdapter, CoverageIngestor, AttributionResolver,
TighteningPrAuthor).

Covers the three behaviors called out in the brief:
- kill-switch disabled -> {"status": "disabled"}
- config gate off -> {"status": "config_disabled"}
- a stable, attributed coverage gain opens exactly one PR
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from auto_tighten.attribution import AttributionResolver
from auto_tighten.coverage_adapter import CoverageAdapter
from auto_tighten.coverage_ingestor import CoverageIngestor
from auto_tighten.models import CoverageRecord
from auto_tighten.observation_store import ObservationStore
from auto_tighten_loop import AutoTightenLoop
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from loop_fitness import FitnessContext, FitnessKind


def _deps(bus: EventBus, *, enabled: bool) -> LoopDeps:
    return LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _seed_pyproject(root: Path, fail_under: float) -> None:
    (root / "pyproject.toml").write_text(
        f"[tool.coverage.report]\nfail_under = {fail_under}\nshow_missing = true\n"
    )


def _seed_coverage_jsonl(path: Path, percents: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        CoverageRecord(
            timestamp=f"2026-07-0{i + 1}T00:00:00Z",
            coverage_percent=pct,
            commit_sha=f"sha{i}",
            run_id=str(i),
        ).model_dump_json()
        for i, pct in enumerate(percents)
    ]
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def make_auto_tighten_loop(tmp_path: Path):
    """Factory fixture building an AutoTightenLoop against real collaborators.

    Kwargs mirror the brief's sketch:
    - enabled: kill-switch (LoopDeps.enabled_cb)
    - config_enabled: auto_tighten_loop_enabled config flag
    - coverage_window: successive coverage.jsonl readings (last N feed the
      stability window; adapter.current() always reads the last line)
    - baseline: pyproject.toml's fail_under seed
    - attributed_pr: PR number AttributionResolver.attribute() returns
      (None -> unattributed, holds)
    """

    def _make(
        *,
        enabled: bool = True,
        config_enabled: bool = True,
        coverage_window: list[float] | None = None,
        baseline: float = 70.0,
        attributed_pr: int | None = 11,
    ) -> AutoTightenLoop:
        repo_root = tmp_path
        _seed_pyproject(repo_root, baseline)

        cov_path = repo_root / ".hydraflow" / "auto_tighten" / "coverage.jsonl"
        if coverage_window:
            _seed_coverage_jsonl(cov_path, coverage_window)

        obs_store = ObservationStore(
            repo_root / ".hydraflow" / "auto_tighten" / "observations.jsonl"
        )
        # Pre-seed the observation window one tick short of stability so the
        # single _do_work() call under test supplies the confirming tick.
        stability_ticks = 3
        if coverage_window and len(coverage_window) > 1:
            from datetime import UTC, datetime

            from auto_tighten.models import Observation

            for pct in coverage_window[:-1]:
                obs_store.append(
                    Observation(
                        ts=datetime.now(UTC).isoformat(),
                        ratchet_id="coverage",
                        current=pct,
                        baseline=baseline,
                        direction="tighter" if pct > baseline else "same",
                    )
                )

        adapter = CoverageAdapter(coverage_jsonl=cov_path, margin=1.0)
        ingestor = CoverageIngestor(cov_path, fetch_latest=lambda: None)
        attribution = AttributionResolver(
            list_merged_prs=lambda since: (
                [{"number": attributed_pr, "files": ["tests/test_x.py"]}]
                if attributed_pr is not None
                else []
            )
        )
        pr_author = AsyncMock()
        pr_author.open.return_value = "https://github.com/hydra/hydraflow/pull/999"

        cfg = HydraFlowConfig(
            data_root=repo_root / ".hydraflow",
            repo="hydra/hydraflow",
            repo_root=repo_root,
            auto_tighten_loop_enabled=config_enabled,
            auto_tighten_stability_ticks=stability_ticks,
            auto_tighten_coverage_margin=1.0,
        )

        bus = EventBus()
        loop = AutoTightenLoop(
            config=cfg,
            state=None,
            deps=_deps(bus, enabled=enabled),
            adapters=[adapter],
            ingestor=ingestor,
            attribution=attribution,
            pr_author=pr_author,
            observation_store=obs_store,
        )
        loop._bus_for_test = bus  # type: ignore[attr-defined]
        return loop

    return _make


async def test_disabled_by_killswitch_returns_disabled(make_auto_tighten_loop):
    loop = make_auto_tighten_loop(enabled=False)
    assert (await loop._do_work())["status"] == "disabled"
    loop._pr_author.open.assert_not_awaited()


async def test_config_gate_returns_config_disabled(make_auto_tighten_loop):
    loop = make_auto_tighten_loop(enabled=True, config_enabled=False)
    assert (await loop._do_work())["status"] == "config_disabled"
    loop._pr_author.open.assert_not_awaited()


async def test_stable_attributed_gain_opens_one_pr(make_auto_tighten_loop):
    loop = make_auto_tighten_loop(
        enabled=True,
        config_enabled=True,
        coverage_window=[78.0, 78.5, 79.0],
        baseline=70.0,
        attributed_pr=11,
    )
    result = await loop._do_work()
    assert result["tightened"] == 1
    loop._pr_author.open.assert_awaited_once()


async def test_unattributed_gain_holds_without_opening_pr(make_auto_tighten_loop):
    loop = make_auto_tighten_loop(
        enabled=True,
        config_enabled=True,
        coverage_window=[78.0, 78.5, 79.0],
        baseline=70.0,
        attributed_pr=None,
    )
    result = await loop._do_work()
    assert result["tightened"] == 0
    loop._pr_author.open.assert_not_awaited()


async def test_looser_coverage_below_baseline_is_refused_without_opening_pr(
    make_auto_tighten_loop,
):
    loop = make_auto_tighten_loop(
        enabled=True,
        config_enabled=True,
        coverage_window=[65.0],
        baseline=70.0,
        attributed_pr=11,
    )
    result = await loop._do_work()
    assert result["status"] == "ok"
    loop._pr_author.open.assert_not_awaited()


async def test_cold_start_with_no_coverage_data_is_a_noop(make_auto_tighten_loop):
    loop = make_auto_tighten_loop(
        enabled=True, config_enabled=True, coverage_window=None
    )
    result = await loop._do_work()
    assert result["status"] == "ok"
    assert result["tightened"] == 0
    loop._pr_author.open.assert_not_awaited()


def test_loop_fitness_is_housekeeping(make_auto_tighten_loop):
    loop = make_auto_tighten_loop()
    ctx = FitnessContext(
        window_start=datetime(2026, 6, 1, tzinfo=UTC),
        window_end=datetime(2026, 6, 30, tzinfo=UTC),
    )
    fitness = loop.loop_fitness(ctx)
    assert fitness.kind is FitnessKind.HOUSEKEEPING
    assert fitness.worker_name == "auto_tighten"


def test_worker_name_and_interval(make_auto_tighten_loop):
    loop = make_auto_tighten_loop()
    assert loop._worker_name == "auto_tighten"
    assert loop._get_default_interval() == loop._config.auto_tighten_interval
