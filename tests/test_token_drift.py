"""Tests for token_drift.py — the read-only drift engine (#11441).

Baseline pinning, drift computation, control-band edge cases, sigma
thresholds, the JSONL ledger round-trip, and the fail-soft error path an
unreadable/corrupt baseline ledger must degrade through (never raise).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from token_drift import (
    MAX_BASELINE_AGE,
    MEDIAN_TOKENS_SOURCE,
    MIN_BASELINE_WINDOWS,
    DriftReport,
    DriftStatus,
    DriftVerdict,
    TokenBaseline,
    TokenBaselineLedger,
    check_drift,
    iso_week_windows,
    load_and_check_drift,
    pin_baseline,
    token_baseline_path,
)
from vitals_methodology import widened_sigma_multiplier

_NOW = datetime(2026, 3, 10, tzinfo=UTC)  # ISO 2026-W11
_TRAILING_WEEK_TS = "2026-03-03T12:00:00+00:00"  # ISO 2026-W10 — one full week earlier
_OLDER_WEEK_TS = "2026-02-24T12:00:00+00:00"  # ISO 2026-W09


def _row(issue: int, source: str, tokens: int, *, ts: str = _TRAILING_WEEK_TS) -> dict:
    return {
        "issue_number": issue,
        "source": source,
        "total_tokens": tokens,
        "timestamp": ts,
    }


def _two_source_window(
    target_share: float,
    *,
    total: int = 1_000_000,
    issue: int = 1,
    ts: str = _TRAILING_WEEK_TS,
) -> list[dict]:
    """One issue split between ``target`` and ``other`` so ``target``'s share
    is (approximately, modulo the report's 3-decimal rounding) *target_share*.
    """
    target_tokens = round(target_share * total)
    return [
        _row(issue, "target", target_tokens, ts=ts),
        _row(issue, "other", total - target_tokens, ts=ts),
    ]


def _baseline(
    *,
    windows_counted: int = MIN_BASELINE_WINDOWS,
    source_share_series: dict[str, list[float]] | None = None,
    median_tokens_series: list[float] | None = None,
    pinned_at: datetime = _NOW - timedelta(days=1),
) -> TokenBaseline:
    return TokenBaseline(
        pinned_at=pinned_at,
        windows_counted=windows_counted,
        source_share_series=(
            source_share_series
            if source_share_series is not None
            else {"target": [0.5] * windows_counted}
        ),
        median_tokens_series=(
            median_tokens_series
            if median_tokens_series is not None
            else [50_000.0] * windows_counted
        ),
    )


# --- iso_week_windows -------------------------------------------------------


class TestIsoWeekWindows:
    def test_buckets_complete_weeks_oldest_first(self) -> None:
        rows = [
            _row(1, "implementer", 10_000, ts=_OLDER_WEEK_TS),
            _row(2, "implementer", 10_000, ts=_TRAILING_WEEK_TS),
        ]
        windows = iso_week_windows(rows, now=_NOW, windows=8)
        assert [week for week, _ in windows] == ["2026-W09", "2026-W10"]

    def test_drops_current_partial_week(self) -> None:
        rows = [
            _row(1, "implementer", 10_000, ts=_TRAILING_WEEK_TS),
            _row(2, "implementer", 10_000, ts=_NOW.isoformat()),
        ]
        windows = iso_week_windows(rows, now=_NOW, windows=8)
        assert len(windows) == 1
        assert sum(len(bucket) for _, bucket in windows) == 1

    def test_drops_unparseable_timestamp_without_raising(self) -> None:
        rows = [
            _row(1, "implementer", 10_000, ts="not-a-timestamp"),
            {"issue_number": 2, "source": "implementer", "total_tokens": 10_000},
        ]
        windows = iso_week_windows(rows, now=_NOW, windows=8)
        assert windows == []

    def test_keeps_only_trailing_n_windows(self) -> None:
        rows = [
            _row(week, "implementer", 10_000, ts=f"2026-01-{week:02d}T00:00:00+00:00")
            for week in range(1, 29, 7)  # four distinct weeks in January
        ]
        windows = iso_week_windows(rows, now=_NOW, windows=2)
        assert len(windows) == 2


# --- pin_baseline ------------------------------------------------------------


class TestPinBaseline:
    def test_pins_per_window_share_and_median_series(self) -> None:
        window_a = [_row(1, "implementer", 80_000), _row(1, "planner", 20_000)]
        window_b = [_row(2, "implementer", 50_000), _row(2, "planner", 50_000)]
        baseline = pin_baseline(
            [("2026-W09", window_a), ("2026-W10", window_b)], pinned_at=_NOW
        )
        assert baseline.windows_counted == 2
        assert baseline.source_share_series["implementer"] == [0.8, 0.5]
        assert baseline.source_share_series["planner"] == [0.2, 0.5]
        assert baseline.median_tokens_series == [100_000.0, 100_000.0]

    def test_source_absent_from_a_window_fills_zero_share(self) -> None:
        window_a = [_row(1, "implementer", 100_000)]
        window_b = [_row(2, "implementer", 50_000), _row(2, "planner", 50_000)]
        baseline = pin_baseline(
            [("2026-W09", window_a), ("2026-W10", window_b)], pinned_at=_NOW
        )
        assert baseline.source_share_series["planner"] == [0.0, 0.5]

    def test_window_with_many_issues_counts_all_of_them(self) -> None:
        rows = [_row(n, "implementer", n * 1_000) for n in range(1, 31)]  # 30 issues
        baseline = pin_baseline([("2026-W10", rows)], pinned_at=_NOW)
        totals = sorted(n * 1_000 for n in range(1, 31))
        expected_median = totals[len(totals) // 2]
        assert baseline.median_tokens_series == [float(expected_median)]


# --- check_drift: guardrails --------------------------------------------------


class TestCheckDriftGuardrails:
    def test_no_baseline_yields_no_baseline_status(self) -> None:
        report = check_drift(None, [], now=_NOW)
        assert report.status is DriftStatus.NO_BASELINE
        assert report.reason
        assert report.sources == []

    def test_baseline_below_min_windows_yields_insufficient_data(self) -> None:
        baseline = _baseline(windows_counted=MIN_BASELINE_WINDOWS - 1)
        report = check_drift(baseline, _two_source_window(0.5), now=_NOW)
        assert report.status is DriftStatus.INSUFFICIENT_DATA
        assert report.reason
        assert report.sources == []

    def test_series_length_mismatch_with_windows_counted_is_corrupt(self) -> None:
        """windows_counted is the row's self-report; the engine does not trust
        it in place of the actual series — a baseline whose series disagree is
        corrupt (never a ZeroDivisionError from an empty chart).
        """
        baseline = TokenBaseline(
            pinned_at=_NOW - timedelta(days=1),
            windows_counted=8,
            source_share_series={},
            median_tokens_series=[],
        )
        report = check_drift(baseline, _two_source_window(0.5), now=_NOW)
        assert report.status is DriftStatus.NO_BASELINE
        assert report.reason

    def test_aged_baseline_yields_stale_with_no_sources(self) -> None:
        baseline = _baseline(pinned_at=_NOW - MAX_BASELINE_AGE - timedelta(days=1))
        report = check_drift(baseline, _two_source_window(0.5), now=_NOW)
        assert report.status is DriftStatus.STALE
        assert report.reason
        assert report.sources == []

    def test_no_issues_in_trailing_window_yields_insufficient_data(self) -> None:
        baseline = _baseline()
        report = check_drift(baseline, [], now=_NOW)
        assert report.status is DriftStatus.INSUFFICIENT_DATA
        assert report.reason

    def test_fleet_idle_in_trailing_week_is_not_ok_on_older_data(self) -> None:
        """The trailing window is the calendar's latest complete week: when
        the fleet was idle that week the instrument is not watching, even
        though older complete weeks still hold data — never an `ok` (let
        alone `drifting`) verdict computed on stale data.
        """
        baseline = _baseline(source_share_series={"target": [0.5] * 8})
        rows = _two_source_window(0.6, ts=_OLDER_WEEK_TS)  # W09; now is W11
        report = check_drift(baseline, rows, now=_NOW)
        assert report.status is DriftStatus.INSUFFICIENT_DATA
        assert report.window_key is None
        assert report.reason

    def test_trailing_window_rows_below_issue_floor_yields_insufficient_data(
        self,
    ) -> None:
        """Rows exist in the trailing week, but every issue is too small to
        count (below token_report.MIN_ISSUE_TOKENS) — distinct from an empty
        trailing window: here a window_key is known, just no countable issue.
        """
        baseline = _baseline()
        tiny_rows = [_row(1, "target", 10)]  # far below MIN_ISSUE_TOKENS
        report = check_drift(baseline, tiny_rows, now=_NOW)
        assert report.status is DriftStatus.INSUFFICIENT_DATA
        assert report.window_key == "2026-W10"


# --- check_drift: payload -----------------------------------------------------


class TestDriftReportPayload:
    def test_carries_window_key_with_monday_and_sunday_dates(self) -> None:
        report = check_drift(_baseline(), _two_source_window(0.5), now=_NOW)
        payload = report.to_json_dict()
        assert payload["window_key"] == "2026-W10"
        assert payload["window_start"] == "2026-03-02"  # Monday
        assert payload["window_end"] == "2026-03-08"  # Sunday

    def test_window_dates_are_null_without_a_window(self) -> None:
        payload = DriftReport(
            status=DriftStatus.NO_BASELINE, reason="no baseline"
        ).to_json_dict()
        assert payload["window_start"] is None
        assert payload["window_end"] is None

    def test_malformed_window_key_yields_null_dates_not_an_error(self) -> None:
        payload = DriftReport(
            status=DriftStatus.OK, reason="r", window_key="2026-W99"
        ).to_json_dict()
        assert payload["window_start"] is None
        assert payload["window_end"] is None


# --- check_drift: verdicts ----------------------------------------------------


class TestCheckDriftVerdicts:
    def test_share_climbing_past_band_is_drifting_with_before_after(self) -> None:
        baseline = _baseline(
            source_share_series={"target": [0.10, 0.14] * 4, "other": [0.5] * 8}
        )
        rows = _two_source_window(0.35)
        report = check_drift(baseline, rows, now=_NOW)
        target = next(s for s in report.sources if s.source == "target")
        assert target.verdict is DriftVerdict.DRIFTING
        assert target.before_share == pytest.approx(0.12)
        assert target.after_share == pytest.approx(0.35, abs=0.001)

    def test_share_wobbling_inside_band_stays_ok(self) -> None:
        baseline = _baseline(
            source_share_series={"target": [0.10, 0.14] * 4, "other": [0.5] * 8}
        )
        rows = _two_source_window(0.20)
        report = check_drift(baseline, rows, now=_NOW)
        target = next(s for s in report.sources if s.source == "target")
        assert target.verdict is DriftVerdict.OK

    def test_share_at_limit_is_ok_strictly_above_is_drifting(self) -> None:
        baseline = _baseline(source_share_series={"target": [0.5] * 8})
        at_limit = check_drift(baseline, _two_source_window(0.5), now=_NOW)
        above_limit = check_drift(baseline, _two_source_window(0.6), now=_NOW)
        target_at = next(s for s in at_limit.sources if s.source == "target")
        target_above = next(s for s in above_limit.sources if s.source == "target")
        assert target_at.verdict is DriftVerdict.OK
        assert target_above.verdict is DriftVerdict.DRIFTING

    def test_zero_dispersion_baseline_breaches_on_any_rise_with_sigma_none(
        self,
    ) -> None:
        baseline = _baseline(source_share_series={"target": [0.5] * 8})
        report = check_drift(baseline, _two_source_window(0.6), now=_NOW)
        target = next(s for s in report.sources if s.source == "target")
        assert target.verdict is DriftVerdict.DRIFTING
        assert target.sigma is None

    def test_source_unseen_at_pin_time_is_unbaselined(self) -> None:
        baseline = _baseline(source_share_series={"implementer": [1.0] * 8})
        rows = [
            _row(1, "implementer", 50_000),
            _row(1, "reviewer", 50_000),
        ]
        report = check_drift(baseline, rows, now=_NOW)
        reviewer = next(s for s in report.sources if s.source == "reviewer")
        assert reviewer.verdict is DriftVerdict.UNBASELINED
        assert reviewer.before_share is None
        assert reviewer.sigma is None
        assert reviewer.is_drifting is False

    def test_median_tokens_breach_is_reported_independently(self) -> None:
        baseline = _baseline(
            source_share_series={"implementer": [1.0] * 8},
            median_tokens_series=[50_000.0] * 8,
        )
        rows = [_row(1, "implementer", 80_000)]
        report = check_drift(baseline, rows, now=_NOW)
        implementer = next(s for s in report.sources if s.source == "implementer")
        median = next(s for s in report.sources if s.source == MEDIAN_TOKENS_SOURCE)
        assert implementer.verdict is DriftVerdict.OK
        assert median.verdict is DriftVerdict.DRIFTING
        assert median.before_share == pytest.approx(50_000.0)
        assert median.after_share == pytest.approx(80_000.0)

    def test_rows_older_than_trailing_window_excluded(self) -> None:
        baseline = _baseline(source_share_series={"target": [0.5] * 8})
        rows = [
            *_two_source_window(0.99, issue=1, ts=_OLDER_WEEK_TS),  # excluded
            *_two_source_window(0.5, issue=2, ts=_TRAILING_WEEK_TS),
        ]
        report = check_drift(baseline, rows, now=_NOW)
        target = next(s for s in report.sources if s.source == "target")
        assert target.after_share == pytest.approx(0.5, abs=0.001)
        assert target.verdict is DriftVerdict.OK

    def test_band_widens_as_charted_source_count_grows(self) -> None:
        series = [0.10, 0.14] * 4  # centre 0.12, sigma_hat != 0
        narrow = _baseline(source_share_series={"target": series})
        wide_sources = {f"dummy{i}": [0.001] * 8 for i in range(299)}
        wide_sources["target"] = series
        wide = _baseline(source_share_series=wide_sources)

        l_narrow = widened_sigma_multiplier(
            len(narrow.source_share_series) + 1, two_sided=False
        )
        l_wide = widened_sigma_multiplier(
            len(wide.source_share_series) + 1, two_sided=False
        )
        assert l_wide > l_narrow  # sanity: the fleet-count effect is real here
        assert l_narrow == 3.0  # the classic floor — 2 charts are far below it

        spread = 0.04 / 1.128
        centre = 0.12
        midpoint = centre + ((l_narrow + l_wide) / 2.0) * spread

        narrow_report = check_drift(narrow, _two_source_window(midpoint), now=_NOW)
        wide_report = check_drift(wide, _two_source_window(midpoint), now=_NOW)
        narrow_target = next(s for s in narrow_report.sources if s.source == "target")
        wide_target = next(s for s in wide_report.sources if s.source == "target")
        assert narrow_target.verdict is DriftVerdict.DRIFTING
        assert wide_target.verdict is DriftVerdict.OK


# --- TokenBaseline JSON round-trip -------------------------------------------


class TestTokenBaselineRoundTrip:
    def test_round_trips_through_json_dict(self) -> None:
        baseline = _baseline()
        restored = TokenBaseline.from_json_dict(baseline.to_json_dict())
        assert restored == baseline

    def test_row_missing_newer_field_still_loads(self) -> None:
        raw = {"pinned_at": _NOW.isoformat()}
        restored = TokenBaseline.from_json_dict(raw)
        assert restored.windows_counted == 0
        assert restored.source_share_series == {}
        assert restored.median_tokens_series == []

    def test_missing_pinned_at_raises(self) -> None:
        with pytest.raises(KeyError):
            TokenBaseline.from_json_dict({"windows_counted": 8})

    def test_naive_pinned_at_raises(self) -> None:
        """A timezone-naive pinned_at parses via fromisoformat without error,
        but `now - pinned_at` in check_drift would raise TypeError later —
        catch it here, at the parse boundary, instead.
        """
        with pytest.raises(ValueError):
            TokenBaseline.from_json_dict({"pinned_at": "2026-01-01T00:00:00"})


# --- TokenBaselineLedger -------------------------------------------------------


class TestTokenBaselineLedger:
    def test_latest_returns_none_when_missing(self, tmp_path: Path) -> None:
        ledger = TokenBaselineLedger(token_baseline_path(tmp_path))
        assert ledger.latest() is None

    def test_path_property_matches_token_baseline_path(self, tmp_path: Path) -> None:
        ledger = TokenBaselineLedger(token_baseline_path(tmp_path))
        assert ledger.path == token_baseline_path(tmp_path)

    def test_record_then_latest_round_trips(self, tmp_path: Path) -> None:
        ledger = TokenBaselineLedger(token_baseline_path(tmp_path))
        baseline = _baseline()
        ledger.record(baseline)
        assert ledger.latest() == baseline

    def test_latest_wins_over_earlier_rows(self, tmp_path: Path) -> None:
        ledger = TokenBaselineLedger(token_baseline_path(tmp_path))
        first = _baseline(windows_counted=8)
        second = _baseline(windows_counted=9, pinned_at=_NOW)
        ledger.record(first)
        ledger.record(second)
        assert ledger.latest() == second

    def test_latest_raises_on_row_missing_required_field(self, tmp_path: Path) -> None:
        path = token_baseline_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"windows_counted": 8}) + "\n", encoding="utf-8")
        ledger = TokenBaselineLedger(path)
        with pytest.raises(KeyError):
            ledger.latest()


# --- load_and_check_drift ------------------------------------------------------


def _fake_config(tmp_path: Path) -> MagicMock:
    config = MagicMock()
    config.data_root = tmp_path
    prompt_dir = tmp_path / "metrics" / "prompt"
    config.cost_inferences_path = prompt_dir / "inferences.jsonl"
    config.pr_stats_path = prompt_dir / "pr_stats.json"
    return config


class TestLoadAndCheckDrift:
    def test_no_ledger_file_yields_no_baseline(self, tmp_path: Path) -> None:
        report = load_and_check_drift(_fake_config(tmp_path), now=_NOW)
        assert report.status is DriftStatus.NO_BASELINE

    def test_degrades_to_no_baseline_on_naive_pinned_at(self, tmp_path: Path) -> None:
        """A ledger row with a timezone-naive pinned_at is corrupt input, not a
        crash: the route must still return a graceful drift block.
        """
        config = _fake_config(tmp_path)
        path = token_baseline_path(config.data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"pinned_at": "2026-01-01T00:00:00", "windows_counted": 8})
            + "\n",
            encoding="utf-8",
        )

        report = load_and_check_drift(config, now=_NOW)

        assert report.status is DriftStatus.NO_BASELINE
        assert report.reason

    def test_degrades_to_no_baseline_on_unreadable_ledger(self, tmp_path: Path) -> None:
        """The error path: a corrupt-but-valid-JSON baseline row must never 500."""
        config = _fake_config(tmp_path)
        path = token_baseline_path(config.data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"windows_counted": 8}) + "\n", encoding="utf-8")

        report = load_and_check_drift(config, now=_NOW)

        assert report.status is DriftStatus.NO_BASELINE
        assert report.reason

    @pytest.mark.parametrize(
        "row",
        [
            # A scalar where the series mapping belongs: dict(5) TypeError.
            {"pinned_at": _NOW.isoformat(), "source_share_series": 5},
            # null inside a series: float(None) TypeError.
            {
                "pinned_at": _NOW.isoformat(),
                "source_share_series": {"target": [0.5, None] * 4},
            },
            # windows_counted claims 8 windows the series do not carry.
            {
                "pinned_at": _NOW.isoformat(),
                "windows_counted": 8,
                "source_share_series": {},
                "median_tokens_series": [],
            },
        ],
        ids=["scalar-series", "null-in-series", "series-window-mismatch"],
    )
    def test_structurally_corrupt_rows_degrade_to_no_baseline(
        self, tmp_path: Path, row: dict
    ) -> None:
        """Structurally corrupt shapes — the ones that would raise TypeError
        or ZeroDivisionError straight through the fail-soft seam and 500 the
        diagnostics route — degrade like any other corrupt row.
        """
        config = _fake_config(tmp_path)
        path = token_baseline_path(config.data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")

        report = load_and_check_drift(config, now=_NOW)

        assert report.status is DriftStatus.NO_BASELINE
        assert report.reason

    def test_reads_baseline_and_computes_drift_end_to_end(self, tmp_path: Path) -> None:
        config = _fake_config(tmp_path)
        TokenBaselineLedger(token_baseline_path(config.data_root)).record(
            _baseline(source_share_series={"target": [0.5] * 8})
        )
        config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config.cost_inferences_path, "w") as f:
            for row in _two_source_window(0.6):
                f.write(json.dumps(row) + "\n")

        report = load_and_check_drift(config, now=_NOW)

        assert report.status is DriftStatus.OK
        target = next(s for s in report.sources if s.source == "target")
        assert target.verdict is DriftVerdict.DRIFTING
