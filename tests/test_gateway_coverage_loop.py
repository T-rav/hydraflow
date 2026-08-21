"""GatewayCoverageLoop unit tests. Generated on 2026-08-19."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gateway_coverage import gateway_coverage_snapshot_path, gateway_ledger_path
from gateway_coverage_loop import GatewayCoverageLoop
from loop_fitness import Confidence, FitnessContext, FitnessKind
from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path: Path, *, enabled: bool = True, **config_overrides):
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **config_overrides)
    state = MagicMock()
    loop = GatewayCoverageLoop(
        config=deps.config,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, state


def _gateway_row(now: datetime, repo_slug: str) -> dict[str, object]:
    return {
        "timestamp": (now - timedelta(minutes=5)).isoformat(),
        "request_id": "req-1",
        "source": "gateway",
        "key_id": "key-1",
        "principal": {
            "kind": "spawn",
            "id": "gateway-coverage-test",
            "spawn_id": "spawn-1",
        },
        "repo_slug": repo_slug,
        "repo_class": "hydraflow",
        "body_capture_policy": "metadata-only",
        "latency_ms": 1.0,
        "status_code": 200,
        "status": "completed",
        "upstream_provider": "anthropic",
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "completed": True,
        "client_aborted": False,
        "observer_malformed_events": 0,
        "cost_usd": 3.0,
        "cost_unknown": False,
    }


def test_worker_name(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    assert loop._worker_name == "gateway_coverage"


def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, gateway_coverage_interval=180)
    assert loop._get_default_interval() == 180


def test_loop_fitness_is_housekeeping(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    context = FitnessContext(
        window_start=datetime(2026, 8, 18, tzinfo=UTC),
        window_end=datetime(2026, 8, 19, tzinfo=UTC),
    )

    fitness = loop.loop_fitness(context)

    assert fitness.kind is FitnessKind.HOUSEKEEPING
    assert fitness.confidence is Confidence.INSUFFICIENT_DATA
    assert fitness.worker_name == "gateway_coverage"
    assert fitness.timestamp == context.window_end


@pytest.mark.asyncio
async def test_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, enabled=False)
    result = await loop._do_work()
    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_static_config_disable_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_COVERAGE_ENABLED", "false")
    loop, _ = _make_loop(tmp_path, enabled=True)
    result = await loop._do_work()
    assert result == {"status": "config_disabled"}


@pytest.mark.asyncio
async def test_tick_persists_repo_scoped_snapshot_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 19, 20, tzinfo=UTC)
    loop, _ = _make_loop(tmp_path)
    config = loop._config
    object.__setattr__(config, "data_root", tmp_path / "data")
    monkeypatch.setattr("gateway_coverage_loop._utcnow", lambda: now)

    ledger = gateway_ledger_path(config)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(_gateway_row(now, config.repo_slug)) + "\n")
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    config.cost_inferences_path.write_text(
        json.dumps(
            {
                "timestamp": (now - timedelta(minutes=4)).isoformat(),
                "source": "wiki_compilation",
                "tool": "openrouter",
                "cost_usd": 1.0,
            }
        )
        + "\n"
    )

    result = await loop._do_work()

    assert result is not None
    assert result["status"] == "ok"
    assert result["coverage_status"] == "complete"
    assert result["coverage_percent"] == 75.0
    snapshot = json.loads(gateway_coverage_snapshot_path(config).read_text())
    assert snapshot["gateway_requests"] == 1
    assert snapshot["bypassing_families"][0]["family"] == "wiki_compilation"


@pytest.mark.asyncio
async def test_post_ceiling_direct_request_trips_durable_regression_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 19, 20, tzinfo=UTC)
    loop, state = _make_loop(tmp_path)
    config = loop._config
    object.__setattr__(config, "data_root", tmp_path / "data")
    monkeypatch.setattr("gateway_coverage_loop._utcnow", lambda: now)
    ceiling_achieved = False

    def has_ceiling() -> bool:
        return ceiling_achieved

    def mark_ceiling() -> None:
        nonlocal ceiling_achieved
        ceiling_achieved = True

    state.gateway_coverage_ceiling_achieved.side_effect = has_ceiling
    state.mark_gateway_coverage_ceiling_achieved.side_effect = mark_ceiling
    state.record_gateway_coverage_regression.return_value = 1
    ledger = gateway_ledger_path(config)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(_gateway_row(now, config.repo_slug)) + "\n")
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    config.cost_inferences_path.write_text("")

    ceiling = await loop._do_work()
    config.cost_inferences_path.write_text(
        json.dumps(
            {
                "timestamp": (now - timedelta(minutes=1)).isoformat(),
                "source": "implementer",
                "tool": "claude",
                "estimated_cost_usd": 1.0,
            }
        )
        + "\n"
    )
    regressed = await loop._do_work()

    assert ceiling is not None
    assert ceiling["ceiling_achieved"] is True
    assert ceiling["regression_detected"] is False
    assert regressed is not None
    assert regressed["coverage_percent"] == 75.0
    assert regressed["regression_detected"] is True
    persisted = json.loads(gateway_coverage_snapshot_path(config).read_text())
    assert persisted["ceiling_achieved"] is True
    assert persisted["regression_detected"] is True
    state.record_gateway_coverage_regression.assert_called_once_with()


@pytest.mark.asyncio
async def test_post_ceiling_corrupt_denominator_trips_regression_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 19, 20, tzinfo=UTC)
    loop, state = _make_loop(tmp_path)
    config = loop._config
    object.__setattr__(config, "data_root", tmp_path / "data")
    monkeypatch.setattr("gateway_coverage_loop._utcnow", lambda: now)
    state.gateway_coverage_ceiling_achieved.return_value = True
    state.record_gateway_coverage_regression.return_value = 1
    ledger = gateway_ledger_path(config)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(_gateway_row(now, config.repo_slug)) + "\n")
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    config.cost_inferences_path.write_text(
        json.dumps(
            {
                "timestamp": "not-a-timestamp",
                "source": "wiki_compilation",
                "tool": "openrouter",
                "estimated_cost_usd": 2.0,
            }
        )
        + "\n"
    )

    result = await loop._do_work()

    assert result is not None
    assert result["coverage_status"] == "partial"
    assert result["coverage_percent"] is None
    assert result["bypass_requests"] == 0
    assert result["regression_detected"] is True
    state.record_gateway_coverage_regression.assert_called_once_with()


@pytest.mark.asyncio
async def test_post_ceiling_missing_source_files_trip_regression_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 19, 20, tzinfo=UTC)
    loop, state = _make_loop(tmp_path)
    config = loop._config
    object.__setattr__(config, "data_root", tmp_path / "data")
    monkeypatch.setattr("gateway_coverage_loop._utcnow", lambda: now)
    ceiling_achieved = False

    def has_ceiling() -> bool:
        return ceiling_achieved

    def mark_ceiling() -> None:
        nonlocal ceiling_achieved
        ceiling_achieved = True

    state.gateway_coverage_ceiling_achieved.side_effect = has_ceiling
    state.mark_gateway_coverage_ceiling_achieved.side_effect = mark_ceiling
    state.record_gateway_coverage_regression.return_value = 1
    ledger = gateway_ledger_path(config)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(_gateway_row(now, config.repo_slug)) + "\n")
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    config.cost_inferences_path.write_text("")

    ceiling = await loop._do_work()
    ledger.unlink()
    config.cost_inferences_path.unlink()
    missing = await loop._do_work()

    assert ceiling is not None
    assert ceiling["ceiling_achieved"] is True
    assert missing is not None
    assert missing["coverage_status"] == "no_data"
    assert missing["regression_detected"] is True
    state.record_gateway_coverage_regression.assert_called_once_with()


@pytest.mark.asyncio
async def test_post_ceiling_truncated_sources_trip_regression_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 19, 20, tzinfo=UTC)
    loop, state = _make_loop(tmp_path)
    config = loop._config
    object.__setattr__(config, "data_root", tmp_path / "data")
    monkeypatch.setattr("gateway_coverage_loop._utcnow", lambda: now)
    ceiling_achieved = False

    def has_ceiling() -> bool:
        return ceiling_achieved

    def mark_ceiling() -> None:
        nonlocal ceiling_achieved
        ceiling_achieved = True

    state.gateway_coverage_ceiling_achieved.side_effect = has_ceiling
    state.mark_gateway_coverage_ceiling_achieved.side_effect = mark_ceiling
    state.record_gateway_coverage_regression.return_value = 1
    ledger = gateway_ledger_path(config)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(_gateway_row(now, config.repo_slug)) + "\n")
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    config.cost_inferences_path.write_text("")

    ceiling = await loop._do_work()
    ledger.write_text("")
    truncated = await loop._do_work()

    assert ceiling is not None
    assert ceiling["ceiling_achieved"] is True
    assert truncated is not None
    assert truncated["coverage_status"] == "no_data"
    assert truncated["regression_detected"] is True
    state.record_gateway_coverage_regression.assert_called_once_with()
