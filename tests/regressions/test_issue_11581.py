"""Regression #11581: the drift loader reads by window, never by row count.

``token_drift.load_and_check_drift`` used to load the newest
``DRIFT_LOAD_LIMIT = 5000`` rows of ``inferences.jsonl`` and hand them to
``check_drift``. Live telemetry carried 24,434 rows in ONE ISO week
(2026-W25, of 31,631 rows in the file): at that rate the still-open week
alone passes 5,000 rows in about a day and a half, after which the trailing
complete week has zero loaded rows (``insufficient_data`` — the #11442
actuator files nothing, precisely in the high-burn weeks the sensor exists
to catch), and a cut that lands mid-week mis-samples the shares instead (a
confident verdict on a partial window). Same rows: full file →
``ok; 1 drifting``, newest 5,000 → ``insufficient_data``.

Pins:

(a) a trailing week of more than 5,000 rows, behind an open week that alone
    exceeds the old cap, is rolled up from ALL its rows — its totals and
    shares are the true ones, whatever the file order;
(b) a window the loader knows it cannot cover completely — the telemetry
    retention floor falls inside it, or the read died mid-stream — yields
    ``insufficient_data``, never a verdict.

Every test anchors ``now`` once and passes it to the engine, so the clock is
self-consistent; the fixture is now-relative regardless.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from config import HydraFlowConfig
from prompt_telemetry import PromptTelemetry
from tests.helpers import ConfigFactory
from token_drift import (
    MIN_BASELINE_WINDOWS,
    DriftStatus,
    DriftVerdict,
    TokenBaselineLedger,
    iso_week_windows,
    load_and_check_drift,
    load_window_rows,
    pin_baseline,
    token_baseline_path,
    trailing_complete_weeks,
)

#: The defect: the fixed row cap the loader used to slice the file to.
OLD_ROW_CAP = 5000

#: Every seeded issue totals this many tokens so the median-tokens chart is
#: flat and only the per-source SHARES can move.
ISSUE_TOTAL_TOKENS = 100_000

# Two alternating steady shapes so σ̂ is non-zero: implementer centre 0.41.
_STEADY: tuple[dict[str, int], dict[str, int]] = (
    {"implementer": 40_000, "reviewer": 60_000},
    {"implementer": 42_000, "reviewer": 58_000},
)
#: The trailing week's true implementer share — far past the band.
TRUE_DRIFTED_SHARE = 0.6


def _config(tmp_path: Path) -> HydraFlowConfig:
    """A REAL config scoped to tmp_path, so the retention field the loader
    reads is the real Pydantic field — a typo'd attribute on a MagicMock
    would silently read back as a (non-int) mock and the guard would pass.
    """
    return ConfigFactory.create(repo_root=tmp_path / "repo").model_copy(
        update={"data_root": tmp_path / "data"}
    )


def _rows(issue: int, split: dict[str, int], ts: datetime) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": ts.isoformat(),
            "issue_number": issue,
            "source": source,
            "total_tokens": tokens,
        }
        for source, tokens in split.items()
    ]


def _append(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _pin_steady_baseline(config: HydraFlowConfig, *, now: datetime) -> None:
    """Seed ``MIN_BASELINE_WINDOWS`` steady weeks into the file and pin them."""
    baseline_rows: list[dict[str, Any]] = []
    for k in range(2, 2 + MIN_BASELINE_WINDOWS):
        baseline_rows += _rows(100 + k, _STEADY[k % 2], now - timedelta(days=7 * k))
    windows = iso_week_windows(baseline_rows, now=now, windows=MIN_BASELINE_WINDOWS)
    TokenBaselineLedger(token_baseline_path(config.data_root)).record(
        pin_baseline(windows, pinned_at=now)
    )
    _append(config.cost_inferences_path, baseline_rows)


def _issues(
    first: int, count: int, split: dict[str, int], ts: datetime
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for issue in range(first, first + count):
        rows += _rows(issue, split, ts)
    return rows


def _implementer(report: Any) -> Any:
    return next(s for s in report.sources if s.source == "implementer")


# --- (a) the whole trailing week is read ---------------------------------------


def test_trailing_week_past_the_old_cap_is_rolled_up_from_every_row(
    tmp_path: Path,
) -> None:
    """6,000 trailing-week rows behind 5,500 open-week rows: the old tail cap
    loaded zero trailing rows (``insufficient_data``). The loader now keeps
    exactly the week's rows, and their totals are the true totals.
    """
    now = datetime.now(UTC)
    config = _config(tmp_path)
    _pin_steady_baseline(config, now=now)
    trailing = _issues(
        1000, 3000, {"implementer": 60_000, "reviewer": 40_000}, now - timedelta(days=7)
    )
    open_week = _issues(9000, 2750, {"implementer": 50_000, "reviewer": 50_000}, now)
    assert len(trailing) > OLD_ROW_CAP and len(open_week) > OLD_ROW_CAP
    _append(config.cost_inferences_path, trailing + open_week)

    window = load_window_rows(config, now=now, windows=1)

    assert window.weeks == trailing_complete_weeks(now, 1)
    assert window.truncation is None
    assert len(window.rows) == len(trailing)
    assert sum(r["total_tokens"] for r in window.rows) == 3000 * ISSUE_TOTAL_TOKENS

    report = load_and_check_drift(config, now=now)

    assert report.status is DriftStatus.OK
    assert report.window_key == window.weeks[0]
    assert _implementer(report).after_share == pytest.approx(TRUE_DRIFTED_SHARE)
    assert _implementer(report).verdict is DriftVerdict.DRIFTING


def test_mid_week_cut_cannot_mis_sample_the_share(tmp_path: Path) -> None:
    """The trailing week is heavy-then-light in FILE order (1,500 issues at
    90% implementer, then 1,500 at 30%): the true share is 60%, but any
    5,000-row tail sees only light issues (30%) and reports a clean week.
    The verdict must come from the whole week.
    """
    now = datetime.now(UTC)
    config = _config(tmp_path)
    _pin_steady_baseline(config, now=now)
    week = now - timedelta(days=7)
    heavy = _issues(1000, 1500, {"implementer": 90_000, "reviewer": 10_000}, week)
    light = _issues(3000, 1500, {"implementer": 30_000, "reviewer": 70_000}, week)
    open_week = _issues(9000, 1500, {"implementer": 50_000, "reviewer": 50_000}, now)
    assert len(heavy) + len(light) > OLD_ROW_CAP
    _append(config.cost_inferences_path, heavy + light + open_week)

    report = load_and_check_drift(config, now=now)

    assert report.status is DriftStatus.OK
    assert _implementer(report).after_share == pytest.approx(TRUE_DRIFTED_SHARE)
    assert _implementer(report).verdict is DriftVerdict.DRIFTING
    assert report.reason.endswith("1 drifting")


# --- (b) a known-truncated window never yields a verdict --------------------------


def test_retention_floor_inside_the_window_withholds_the_verdict(
    tmp_path: Path,
) -> None:
    """RunsGCLoop prunes telemetry older than the retention floor. A floor
    inside the trailing week means its head may already be gone — the rows
    that ARE there would read as drifting, and the engine must not say so.
    """
    now = datetime.now(UTC)
    config = _config(tmp_path)
    _pin_steady_baseline(config, now=now)
    _append(
        config.cost_inferences_path,
        _issues(
            1000,
            10,
            {"implementer": 60_000, "reviewer": 40_000},
            now - timedelta(days=7),
        ),
    )
    short_retention = config.model_copy(
        update={"audit_retention_days_inference_telemetry": 3}
    )
    assert load_and_check_drift(config, now=now).status is DriftStatus.OK  # control

    window = load_window_rows(short_retention, now=now, windows=1)
    report = load_and_check_drift(short_retention, now=now)

    assert window.truncation is not None
    assert "retention" in window.truncation
    assert report.status is DriftStatus.INSUFFICIENT_DATA
    assert "retention" in report.reason
    assert report.window_key == window.weeks[0]
    assert report.sources == []


def test_read_that_dies_mid_stream_withholds_the_verdict(tmp_path: Path) -> None:
    """Rows already streamed cannot be retracted: a read that fails part-way
    is a truncated window, not a smaller one."""
    now = datetime.now(UTC)
    config = _config(tmp_path)
    _pin_steady_baseline(config, now=now)
    drifted = _issues(
        1000, 10, {"implementer": 60_000, "reviewer": 40_000}, now - timedelta(days=7)
    )
    _append(config.cost_inferences_path, drifted)

    def _dies_after_first_row(self: PromptTelemetry) -> Iterator[dict[str, Any]]:
        yield drifted[0]
        raise OSError("Input/output error")

    with patch.object(PromptTelemetry, "iter_inferences", _dies_after_first_row):
        window = load_window_rows(config, now=now, windows=1)
        report = load_and_check_drift(config, now=now)

    assert window.rows == [drifted[0]]
    assert window.truncation is not None
    assert report.status is DriftStatus.INSUFFICIENT_DATA
    assert "unreadable" in report.reason
    assert report.sources == []
