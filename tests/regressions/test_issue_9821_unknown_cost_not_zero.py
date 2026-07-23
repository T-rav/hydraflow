"""Regression #9821: unpriced-model cost must surface as unknown, not $0.

Three of the four ``model_pricing`` consumers used to collapse an
unknown-model estimate (``estimate_cost`` → ``None``) into ``0.0``:

* ``runners.base_subprocess_runner._estimate_cost`` — ``float(estimate or 0.0)``
* ``dashboard_routes._waterfall_builder._action_llm`` — ``... if cost is not None else 0.0``
* ``dashboard_routes._cost_rollups.iter_priced_inferences`` — same collapse

which made spend on any model missing from ``src/assets/model_pricing.json``
indistinguishable from genuinely-free traffic. These pins use the REAL
pricing table (not a mock) with a model id that matches no entry or alias,
and assert every cost surface carries an explicit unknown/unpriced marker:

* priced rows: ``cost_unknown`` False / ``unpriced_calls`` 0;
* unpriced rows: ``cost_unknown`` True and aggregated ``unpriced_calls`` /
  ``unpriced_tokens_*`` counters on the rollup + waterfall payloads;
* the subprocess runner returns ``None`` (unknown), and ``SpawnOutcome`` /
  the preflight comment render "cost unknown" instead of ``$0.00``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from config import HydraFlowConfig
from dashboard_routes._cost_rollups import (
    build_cost_by_model,
    build_rolling_24h,
    iter_priced_inferences,
)
from dashboard_routes._waterfall_builder import build_waterfall
from model_pricing import load_pricing
from preflight.decision import PreflightResult, _format_comment
from tests.helpers import ConfigFactory

# No pricing entry or alias is a substring of this id (aliases include bare
# "sonnet"/"opus"/"haiku"/"kimi", so the id must avoid them all).
_UNPRICED_MODEL = "unpriced-model-9821"
_PRICED_MODEL = "claude-sonnet-4-6"


@pytest.fixture
def config(tmp_path: Path) -> HydraFlowConfig:
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return ConfigFactory.create(repo_root=tmp_path / "repo")


def _write_inference(config: HydraFlowConfig, **fields) -> None:
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    with config.cost_inferences_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def test_real_pricing_table_has_no_entry_for_sentinel_model() -> None:
    """Guard: the sentinel model must stay absent from the managed asset."""
    assert load_pricing().estimate_cost(_UNPRICED_MODEL, 100, 50) is None


def test_iter_priced_inferences_marks_unpriced_rows_cost_unknown(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model=_UNPRICED_MODEL,
        issue_number=7,
        input_tokens=100,
        output_tokens=50,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model=_PRICED_MODEL,
        issue_number=7,
        input_tokens=100,
        output_tokens=50,
    )

    rows = list(
        iter_priced_inferences(
            config,
            since=now - timedelta(hours=24),
            until=now,
            pricing=load_pricing(),
        )
    )

    by_model = {r["model"]: r for r in rows}
    assert by_model[_UNPRICED_MODEL]["cost_usd"] == 0.0
    assert by_model[_UNPRICED_MODEL]["cost_unknown"] is True
    assert by_model[_PRICED_MODEL]["cost_unknown"] is False
    assert by_model[_PRICED_MODEL]["cost_usd"] > 0.0


def test_rolling_24h_total_aggregates_unpriced_counters(config, monkeypatch) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: now)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model=_UNPRICED_MODEL,
        issue_number=7,
        input_tokens=100,
        output_tokens=50,
    )

    payload = build_rolling_24h(config, pricing=load_pricing())

    assert payload["total"]["unpriced_calls"] == 1
    assert payload["total"]["unpriced_tokens_in"] == 100
    assert payload["total"]["unpriced_tokens_out"] == 50
    by_phase = {r["phase"]: r for r in payload["by_phase"]}
    assert by_phase["implement"]["unpriced_calls"] == 1


def test_cost_by_model_row_carries_unpriced_calls(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    for model in (_UNPRICED_MODEL, _PRICED_MODEL):
        _write_inference(
            config,
            timestamp=(now - timedelta(hours=1)).isoformat(),
            source="implementer",
            model=model,
            issue_number=7,
            input_tokens=100,
            output_tokens=50,
        )

    rows = build_cost_by_model(
        config,
        since=now - timedelta(hours=24),
        until=now,
        pricing=load_pricing(),
    )

    by_model = {r["model"]: r for r in rows}
    assert by_model[_UNPRICED_MODEL]["unpriced_calls"] == 1
    assert by_model[_UNPRICED_MODEL]["cost_usd"] == 0.0
    assert by_model[_PRICED_MODEL]["unpriced_calls"] == 0


def test_waterfall_marks_unpriced_action_and_counts_it(config) -> None:
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="implementer",
        model=_UNPRICED_MODEL,
        issue_number=9821,
        input_tokens=100,
        output_tokens=50,
    )

    result = build_waterfall(
        config,
        issue=9821,
        issue_meta={"number": 9821, "title": "t", "labels": []},
        pricing=load_pricing(),
    )

    impl = next(p for p in result["phases"] if p["phase"] == "implement")
    assert impl["actions"][0]["cost_unknown"] is True
    assert impl["unpriced_calls"] == 1
    assert result["total"]["unpriced_calls"] == 1


def test_subprocess_runner_estimate_returns_none_for_unpriced_model() -> None:
    from unittest.mock import MagicMock

    from runners.base_subprocess_runner import BaseSubprocessRunner, SpawnOutcome

    class _Runner(BaseSubprocessRunner[SpawnOutcome]):
        def _telemetry_source(self) -> str:
            return "regression_9821"

        def _build_command(self, prompt: str, worktree: Path) -> list[str]:
            return ["true"]

        def _make_result(self, outcome: SpawnOutcome) -> SpawnOutcome:
            return outcome

    runner = _Runner(
        config=ConfigFactory.create(model=_UNPRICED_MODEL), event_bus=MagicMock()
    )
    estimate = runner._estimate_cost({"input_tokens": 100, "output_tokens": 50})
    assert estimate is None


def test_preflight_comment_renders_cost_unknown_not_zero_dollars() -> None:
    result = PreflightResult(
        status="retry",
        pr_url=None,
        diagnosis="diag",
        cost_usd=0.0,
        wall_clock_s=30.0,
        tokens=1000,
        cost_unknown=True,
    )
    comment = _format_comment("flaky-test-stuck", result, 1, False, 3)
    assert "cost unknown" in comment
    assert "$0.00" not in comment
