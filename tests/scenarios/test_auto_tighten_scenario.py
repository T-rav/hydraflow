"""MockWorld scenario for AutoTightenLoop (auto-tighten ratchet).

Drives the loop end-to-end through the ``_build_auto_tighten`` catalog
builder (Task 13) against a real ``CoverageAdapter``, real
``TighteningEngine`` (exercised indirectly via the loop), and a real
``ObservationStore`` rooted at ``tmp_path``. A pre-seeded ``coverage.jsonl``
plus ``pyproject.toml`` ``fail_under`` stand in for CI-produced coverage
data; the ``CoverageIngestor`` is a no-op MagicMock since the data is
seeded directly rather than fetched.  Only the PR-author / gh boundary is
faked (``AsyncMock``); the ``AttributionResolver`` is the real class wired
to a stub ``list_merged_prs`` callable — mirrors
``tests/test_auto_tighten_loop.py``'s ``make_auto_tighten_loop`` fixture,
but built through the scenario catalog + ``seed_ports`` harness like
``tests/scenarios/test_adr_conformance_scenario.py``.

Four cases (the cross-tick open-PR dedup probe is deferred to a
pre-enable follow-up — see the brief's note that a stuck PR is a benign
hold under ``raise_on_failure=False``, not a true skip, so a "no
duplicate PR on second tick" assertion would not hold today):

1. Stable + attributed gain across ``stability_ticks`` ticks -> opens
   exactly one PR.
2. Coverage jittering within the margin -> opens no PR.
3. Unattributed gain -> holds, emits ``RATCHET_TIGHTENED{unattributed:True}``.
4. Looser reading (current below baseline) -> opens no PR, direction
   recorded as "looser".
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_tighten.attribution import AttributionResolver
from auto_tighten.coverage_adapter import CoverageAdapter
from auto_tighten.models import CoverageRecord, Observation
from auto_tighten.observation_store import ObservationStore
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus, EventType
from tests.scenarios.catalog.loop_registrations import _build_auto_tighten
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

_STABILITY_TICKS = 3
_MARGIN = 1.0


def _seed_pyproject(repo_root: Path, fail_under: float) -> None:
    (repo_root / "pyproject.toml").write_text(
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


def _seed_repo(tmp_path: Path, *, baseline: float) -> Path:
    """Seed a minimal repo layout: pyproject.toml fail_under only."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _seed_pyproject(repo_root, baseline)
    return repo_root


def _build_loop(
    world: MockWorld,
    repo_root: Path,
    *,
    coverage_window: list[float],
    baseline: float,
    attributed_pr: int | None,
):
    """Construct AutoTightenLoop via the Task 13 catalog builder.

    Pre-seeds the observation window one tick short of stability (matching
    ``make_auto_tighten_loop`` in ``tests/test_auto_tighten_loop.py``) so
    the single ``_do_work()`` call under test supplies the confirming
    tick — the last entry of ``coverage_window`` is what the adapter reads
    as "current" this tick; the earlier entries seed prior ticks' history.
    """
    config = HydraFlowConfig(
        data_root=repo_root / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=repo_root,
        auto_tighten_loop_enabled=True,
        auto_tighten_stability_ticks=_STABILITY_TICKS,
        auto_tighten_coverage_margin=_MARGIN,
    )
    bus = EventBus()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=world._harness.stop_event,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )

    cov_path = repo_root / ".hydraflow" / "auto_tighten" / "coverage.jsonl"
    _seed_coverage_jsonl(cov_path, coverage_window)

    obs_store = ObservationStore(
        repo_root / ".hydraflow" / "auto_tighten" / "observations.jsonl"
    )
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

    adapter = CoverageAdapter(coverage_jsonl=cov_path, margin=_MARGIN)
    attribution = AttributionResolver(
        list_merged_prs=lambda since: (
            [{"number": attributed_pr, "files": ["tests/test_x.py"]}]
            if attributed_pr is not None
            else []
        )
    )
    pr_author = AsyncMock()
    pr_author.open.return_value = "https://github.com/hydra/hydraflow/pull/999"

    _seed_ports(
        world,
        pr_manager=world.github,
        auto_tighten_obs=obs_store,
        auto_tighten_adapters=[adapter],
        auto_tighten_ingestor=MagicMock(ingest=lambda: None),
        auto_tighten_attribution=attribution,
        auto_tighten_pr_author=pr_author,
    )

    loop = _build_auto_tighten(world._loop_ports, config, deps)
    return loop, config, bus, pr_author


class TestAutoTightenScenario:
    """Auto-tighten ratchet — AutoTightenLoop end-to-end MockWorld scenarios."""

    async def test_stable_attributed_gain_opens_one_pr(self, tmp_path) -> None:
        """Coverage climbs and holds for stability_ticks -> exactly one PR."""
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path, baseline=70.0)
        loop, _config, bus, pr_author = _build_loop(
            world,
            repo_root,
            coverage_window=[78.0, 78.5, 79.0],
            baseline=70.0,
            attributed_pr=11,
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["tightened"] == 1
        pr_author.open.assert_awaited_once()

        history = bus.get_history()
        tightened_events = [e for e in history if e.type == EventType.RATCHET_TIGHTENED]
        assert len(tightened_events) == 1
        assert tightened_events[0].data.get("unattributed") is not True
        assert tightened_events[0].data["pr_url"] == (
            "https://github.com/hydra/hydraflow/pull/999"
        )

    async def test_jitter_within_margin_opens_no_pr(self, tmp_path) -> None:
        """Coverage bounces within the margin -> confirmed floor never
        clears baseline, so no PR is opened.

        baseline=70, margin=1.0, readings 70.5/71.0/70.5: the weakest
        (min) of the stability window is 70.5, minus the 1.0 margin gives
        a proposed floor of 69.5 -- not tighter than the 70.0 baseline, so
        ``TighteningEngine.confirm`` returns None and the tick holds.
        """
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path, baseline=70.0)
        loop, _config, bus, pr_author = _build_loop(
            world,
            repo_root,
            coverage_window=[70.5, 71.0, 70.5],
            baseline=70.0,
            attributed_pr=11,
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["tightened"] == 0
        pr_author.open.assert_not_awaited()

        history = bus.get_history()
        assert not [e for e in history if e.type == EventType.RATCHET_TIGHTENED]

    async def test_unattributed_gain_holds_and_emits_unattributed_event(
        self, tmp_path
    ) -> None:
        """A confirmed gain with no attributing PR holds -- no PR opened,
        RATCHET_TIGHTENED carries unattributed=True."""
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path, baseline=70.0)
        loop, _config, bus, pr_author = _build_loop(
            world,
            repo_root,
            coverage_window=[78.0, 78.5, 79.0],
            baseline=70.0,
            attributed_pr=None,
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["tightened"] == 0
        assert result["held"] == 1
        pr_author.open.assert_not_awaited()

        history = bus.get_history()
        tightened_events = [e for e in history if e.type == EventType.RATCHET_TIGHTENED]
        assert len(tightened_events) == 1
        assert tightened_events[0].data["unattributed"] is True
        assert tightened_events[0].data["ratchet_id"] == "coverage"

    async def test_looser_reading_opens_no_pr(self, tmp_path) -> None:
        """Coverage below baseline is classified "looser" -- recorded as
        an observation, never confirmed/actuated, no PR opened."""
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path, baseline=70.0)
        loop, _config, bus, pr_author = _build_loop(
            world,
            repo_root,
            coverage_window=[65.0],
            baseline=70.0,
            attributed_pr=11,
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["tightened"] == 0
        pr_author.open.assert_not_awaited()

        history = bus.get_history()
        assert not [e for e in history if e.type == EventType.RATCHET_TIGHTENED]

        obs_store = world._loop_ports["auto_tighten_obs"]
        window = obs_store.window("coverage", limit=10)
        assert len(window) == 1
        assert window[-1].direction == "looser"
