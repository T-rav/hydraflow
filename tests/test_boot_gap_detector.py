"""Tests for boot_gap_detector (#10009): boot-time "factory was down" surface.

Covers the pure decision function (compute_boot_gap_alert) exhaustively and
the tail-read helper (last_event_timestamp) against real files on disk.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from boot_gap_detector import compute_boot_gap_alert, last_event_timestamp


def _write_events(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


class TestLastEventTimestamp:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert last_event_timestamp(tmp_path / "nope.jsonl") is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = _write_events(tmp_path, [])
        assert last_event_timestamp(path) is None

    @pytest.mark.parametrize(
        ("last_line", "expected_day"),
        [
            pytest.param(
                '{"id": 2, "timestamp": "2026-07-02T00:00:00+00:00"}',
                2,
                id="reads_timestamp_of_last_line",
            ),
            pytest.param(
                "not json at all {{{", 1, id="falls_back_past_corrupt_trailing_line"
            ),
            pytest.param(
                '{"id": 2, "no_timestamp": true}',
                1,
                id="falls_back_past_line_missing_timestamp_field",
            ),
            pytest.param("[1, 2, 3]", 1, id="json_non_dict_line_skipped"),
        ],
    )
    def test_reads_back_to_the_last_usable_line(
        self, tmp_path: Path, last_line: str, expected_day: int
    ) -> None:
        """Day 2 when the trailing line is usable, day 1 when it must be skipped."""
        path = _write_events(
            tmp_path,
            ['{"id": 1, "timestamp": "2026-07-01T00:00:00+00:00"}', last_line],
        )
        assert last_event_timestamp(path) == datetime(2026, 7, expected_day, tzinfo=UTC)

    def test_naive_timestamp_is_treated_as_utc(self, tmp_path: Path) -> None:
        path = _write_events(
            tmp_path, ['{"id": 1, "timestamp": "2026-07-02T00:00:00"}']
        )
        ts = last_event_timestamp(path)
        assert ts == datetime(2026, 7, 2, tzinfo=UTC)

    def test_blank_trailing_lines_skipped(self, tmp_path: Path) -> None:
        path = _write_events(
            tmp_path,
            [
                '{"id": 1, "timestamp": "2026-07-01T00:00:00+00:00"}',
                "",
                "   ",
            ],
        )
        ts = last_event_timestamp(path)
        assert ts == datetime(2026, 7, 1, tzinfo=UTC)

    def test_all_lines_unparseable_returns_none(self, tmp_path: Path) -> None:
        path = _write_events(tmp_path, ["{{{ broken", "also broken"])
        assert last_event_timestamp(path) is None


class TestComputeBootGapAlert:
    def test_no_last_event_never_alerts(self) -> None:
        alert = compute_boot_gap_alert(
            last_event_at=None,
            boot_at=datetime.now(UTC),
            threshold_seconds=600,
        )
        assert alert is None

    def test_gap_under_threshold_no_alert(self) -> None:
        boot_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        last = boot_at - timedelta(minutes=5)
        alert = compute_boot_gap_alert(
            last_event_at=last, boot_at=boot_at, threshold_seconds=600
        )
        assert alert is None

    def test_gap_exactly_at_threshold_no_alert(self) -> None:
        boot_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        last = boot_at - timedelta(seconds=600)
        alert = compute_boot_gap_alert(
            last_event_at=last, boot_at=boot_at, threshold_seconds=600
        )
        assert alert is None

    def test_gap_over_threshold_alerts(self) -> None:
        boot_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        last = boot_at - timedelta(hours=3)
        alert = compute_boot_gap_alert(
            last_event_at=last, boot_at=boot_at, threshold_seconds=600
        )
        assert alert is not None
        assert alert["source"] == "boot_gap_detector"
        assert alert["severity"] == "warning"
        assert "factory was down ~3.0h" in alert["message"]

    def test_naive_last_event_treated_as_utc(self) -> None:
        boot_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        last_naive = datetime(2026, 7, 19, 9, 0)  # noqa: DTZ001 — exercising naive input
        alert = compute_boot_gap_alert(
            last_event_at=last_naive, boot_at=boot_at, threshold_seconds=600
        )
        assert alert is not None
        assert "3.0h" in alert["message"]

    def test_negative_gap_never_alerts(self) -> None:
        """An event timestamped after boot (clock skew / replay artifact)
        must never alert — there is no "down" period to report."""
        boot_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        last = boot_at + timedelta(hours=1)
        alert = compute_boot_gap_alert(
            last_event_at=last, boot_at=boot_at, threshold_seconds=600
        )
        assert alert is None
