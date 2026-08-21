"""Tests for scripts/pin_token_baseline.py — the operator pin/re-pin CLI.

The engine (``token_drift``) is covered by ``test_token_drift.py``; these
tests cover the script's own contract: dry-run by default (print, never
write), ``--apply`` writes the append-only ledger, too few telemetry windows
refuses to pin instead of pinning a thin baseline, and ``--reason`` is
required so a re-pin always states why it discarded the old steady state.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from token_drift import (
    MIN_BASELINE_WINDOWS,
    TokenBaseline,
    TokenBaselineLedger,
    token_baseline_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "pin_token_baseline.py"


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pin_token_baseline", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_config(tmp_path: Path) -> MagicMock:
    config = MagicMock()
    config.data_root = tmp_path
    prompt_dir = tmp_path / "metrics" / "prompt"
    config.cost_inferences_path = prompt_dir / "inferences.jsonl"
    config.pr_stats_path = prompt_dir / "pr_stats.json"
    config.audit_retention_days_inference_telemetry = None  # keep forever
    return config


def _write_rows(config: MagicMock, rows: list[dict[str, object]]) -> None:
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    config.cost_inferences_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def _write_weeks_of_telemetry(config: MagicMock, *, weeks: int) -> None:
    """Write one two-source issue into each of the trailing *weeks* complete
    ISO weeks.

    The script reads the real clock, so timestamps are spaced 7 days back from
    a test-computed ``now`` (each lands in a distinct ISO week). One extra row
    in the test's own still-open week (``k = 0``) absorbs the midnight race
    where the test's ``now`` and the script's ``now`` straddle a week boundary:
    the loader scans the *weeks* complete calendar weeks before the script's
    ``now`` (#11581), so that row is dropped as open-week data on a normal run
    and counted as the newest complete week when the race shifts the span.
    """
    now = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for k in range(weeks, -1, -1):  # oldest first, as the live file is appended
        ts = (now - timedelta(days=7 * k)).isoformat()
        for source, tokens in (("target", 600), ("other", 400)):
            rows.append(
                {
                    "issue_number": 100 + k,
                    "source": source,
                    "total_tokens": tokens,
                    "timestamp": ts,
                }
            )
    _write_rows(config, rows)


# --- dry run vs apply -----------------------------------------------------------


def test_default_is_dry_run_prints_report_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _load_cli()
    config = _fake_config(tmp_path)
    _write_weeks_of_telemetry(config, weeks=MIN_BASELINE_WINDOWS)

    code = cli.run(
        config, windows=MIN_BASELINE_WINDOWS, reason="post-lever re-pin", apply=False
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "post-lever re-pin" in out
    assert not token_baseline_path(config.data_root).exists()


def test_apply_writes_ledger_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _load_cli()
    config = _fake_config(tmp_path)
    _write_weeks_of_telemetry(config, weeks=MIN_BASELINE_WINDOWS)

    code = cli.run(
        config, windows=MIN_BASELINE_WINDOWS, reason="post-lever re-pin", apply=True
    )

    assert code == 0
    assert "pinned:" in capsys.readouterr().out
    baseline = TokenBaselineLedger(token_baseline_path(config.data_root)).latest()
    assert isinstance(baseline, TokenBaseline)
    assert baseline.windows_counted == MIN_BASELINE_WINDOWS
    assert sorted(baseline.source_share_series) == ["other", "target"]
    # One issue per week at 1000 tokens: the median-tokens series is flat 1000.
    assert baseline.median_tokens_series == [1000.0] * MIN_BASELINE_WINDOWS


# --- guardrails -----------------------------------------------------------------


def test_too_few_windows_refuses_to_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _load_cli()
    config = _fake_config(tmp_path)
    _write_weeks_of_telemetry(config, weeks=2)

    code = cli.run(
        config, windows=MIN_BASELINE_WINDOWS, reason="post-lever re-pin", apply=True
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "window(s) of telemetry available" in err
    assert not token_baseline_path(config.data_root).exists()


def test_retention_floor_inside_the_span_refuses_to_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Telemetry older than the retention floor may already be pruned by
    RunsGCLoop: a span reaching past it would pin a partial oldest week as if
    it were whole (#11581). Refuse, and say why, rather than pin a lie.
    """
    cli = _load_cli()
    config = _fake_config(tmp_path)
    _write_weeks_of_telemetry(config, weeks=MIN_BASELINE_WINDOWS)
    config.audit_retention_days_inference_telemetry = 14

    code = cli.run(
        config, windows=MIN_BASELINE_WINDOWS, reason="post-lever re-pin", apply=True
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "retention" in err
    assert "Not pinning" in err
    assert not token_baseline_path(config.data_root).exists()


def test_busy_weeks_past_the_old_row_cap_pin_from_every_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Eight weeks of 700 rows (5,600 — past the removed 5,000-row cap),
    oldest first as the live file is appended. Each week is heavy-then-light
    in FILE order (target share .9 then .3; the whole week is .6): a
    row-capped read saw only the tail of the oldest week and pinned .3 for
    it as though that were the week (#11581).
    """
    cli = _load_cli()
    config = _fake_config(tmp_path)
    now = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for k in range(MIN_BASELINE_WINDOWS, -1, -1):  # k = 0 absorbs the midnight race
        ts = (now - timedelta(days=7 * k)).isoformat()
        for i in range(350):
            target, other = (900, 100) if i < 175 else (300, 700)
            issue = 10_000 * (k + 1) + i
            rows.append(
                {
                    "issue_number": issue,
                    "source": "target",
                    "total_tokens": target,
                    "timestamp": ts,
                }
            )
            rows.append(
                {
                    "issue_number": issue,
                    "source": "other",
                    "total_tokens": other,
                    "timestamp": ts,
                }
            )
    assert len(rows) > 5000
    _write_rows(config, rows)

    code = cli.run(
        config, windows=MIN_BASELINE_WINDOWS, reason="post-lever re-pin", apply=True
    )

    assert code == 0, capsys.readouterr().err
    baseline = TokenBaselineLedger(token_baseline_path(config.data_root)).latest()
    assert isinstance(baseline, TokenBaseline)
    assert baseline.windows_counted == MIN_BASELINE_WINDOWS
    assert baseline.source_share_series["target"] == [0.6] * MIN_BASELINE_WINDOWS


def test_reason_is_required() -> None:
    """``--apply`` without ``--reason`` must fail argparse, not prompt a pin."""
    cli = _load_cli()
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--apply"])
    assert excinfo.value.code == 2
