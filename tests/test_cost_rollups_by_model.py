"""Tests for build_cost_by_model (cross-loop per-model aggregator)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from config import HydraFlowConfig
from dashboard_routes._cost_rollups import build_cost_by_model
from tests.helpers import ConfigFactory


def _write_inference(config: HydraFlowConfig, **fields) -> None:
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    with config.cost_inferences_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


@pytest.fixture
def config(tmp_path: Path) -> HydraFlowConfig:
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return ConfigFactory.create(repo_root=tmp_path / "repo")


def test_build_cost_by_model_returns_one_row_per_model_sorted_descending(
    config,
) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=100_000,
        output_tokens=20_000,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-haiku-4-5-20251001",
        input_tokens=100_000,
        output_tokens=20_000,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-sonnet-4-6",
        input_tokens=100_000,
        output_tokens=20_000,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert [r["model"] for r in rows] == [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    ]
    for row in rows:
        assert row["calls"] == 1
        assert row["cost_usd"] > 0
        assert "input_tokens" in row
        assert "output_tokens" in row
        assert "cache_read_tokens" in row
        assert "cache_write_tokens" in row


def test_build_cost_by_model_returns_empty_list_for_no_data(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)
    assert rows == []


def test_build_cost_by_model_respects_window(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=1_000,
        output_tokens=100,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(days=8)).isoformat(),
        source="implementer",
        model="claude-sonnet-4-6",
        input_tokens=1_000,
        output_tokens=100,
    )

    rows = build_cost_by_model(config, since=now - timedelta(days=7), until=now)

    assert [r["model"] for r in rows] == ["claude-opus-4-7"]


def test_build_cost_by_model_handles_unpriced_model(config) -> None:
    """Unknown model: cost is 0, tokens still summed."""
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-future-99",
        input_tokens=5_000,
        output_tokens=500,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert len(rows) == 1
    assert rows[0]["model"] == "claude-future-99"
    assert rows[0]["cost_usd"] == 0.0
    assert rows[0]["input_tokens"] == 5_000
    assert rows[0]["output_tokens"] == 500


def test_build_cost_by_model_buckets_missing_model_as_unknown(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="",
        input_tokens=100,
        output_tokens=50,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert [r["model"] for r in rows] == ["unknown"]
    assert rows[0]["calls"] == 1


def test_build_cost_by_model_marks_healthy_rows_cost_plausible(config) -> None:
    """Correctly billed rows carry cost_plausibility == None (#10775)."""
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=100_000,
        output_tokens=20_000,
        cache_read_input_tokens=50_000,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert len(rows) == 1
    assert rows[0]["cost_plausibility"] is None


def test_build_cost_by_model_flags_implausible_cost_and_warns(config, caplog) -> None:
    """A model whose recorded cost is dominated by a char-estimate fallback over
    a tiny real-token base has an effective $/token far above its peak table
    rate — build_cost_by_model surfaces the anomaly and logs a WARNING, without
    failing or zeroing the cost (#10775)."""
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    # Real-token row: 1,000 input tokens of glm-5.2 (peak table rate $4.40/M).
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="glm-5.2",
        input_tokens=1_000,
        output_tokens=0,
    )
    # Char-estimate fallback row: large stored cost, zero tokens (#9821 path).
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="glm-5.2",
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=1.0,
    )

    with caplog.at_level(logging.WARNING, logger="hydraflow.dashboard.cost_rollups"):
        rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == "glm-5.2"
    # Cost is untouched: real ~$0.0014 + $1.00 estimate, never zeroed.
    assert row["cost_usd"] > 1.0
    anomaly = row["cost_plausibility"]
    assert anomaly is not None
    assert anomaly["peak_rate_per_million"] == 4.40
    assert anomaly["ratio"] > 3.0
    assert any("Cost-plausibility anomaly" in rec.message for rec in caplog.records)


def test_cost_plausibility_threshold_is_configurable(config) -> None:
    """Raising the K knob past the observed ratio suppresses the flag (#10775)."""
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="glm-5.2",
        input_tokens=1_000,
        output_tokens=0,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="glm-5.2",
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=1.0,
    )

    config.cost_plausibility_max_rate_multiple = 1_000_000.0
    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert rows[0]["cost_plausibility"] is None
