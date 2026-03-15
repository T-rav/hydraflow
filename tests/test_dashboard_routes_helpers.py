"""Tests for extracted module-level helpers in dashboard_routes.py."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard_routes import (
    _aggregate_telemetry_record,
    _build_history_links,
    _build_hitl_context,
    _build_issue_history_entry,
    _filter_rows_to_items,
    _new_issue_history_entry,
    _normalise_summary_lines,
    _process_events_into_rows,
    _touch_issue_timestamps,
)


class TestTouchIssueTimestamps:
    def test_sets_first_and_last_when_empty(self) -> None:
        row: dict[str, Any] = {"first_seen": None, "last_seen": None}
        _touch_issue_timestamps(row, "2026-01-01T00:00:00")
        assert row["first_seen"] == "2026-01-01T00:00:00"
        assert row["last_seen"] == "2026-01-01T00:00:00"

    def test_updates_last_seen_when_later(self) -> None:
        row: dict[str, Any] = {
            "first_seen": "2026-01-01T00:00:00",
            "last_seen": "2026-01-01T00:00:00",
        }
        _touch_issue_timestamps(row, "2026-01-02T00:00:00")
        assert row["first_seen"] == "2026-01-01T00:00:00"
        assert row["last_seen"] == "2026-01-02T00:00:00"

    def test_updates_first_seen_when_earlier(self) -> None:
        row: dict[str, Any] = {
            "first_seen": "2026-01-02T00:00:00",
            "last_seen": "2026-01-02T00:00:00",
        }
        _touch_issue_timestamps(row, "2026-01-01T00:00:00")
        assert row["first_seen"] == "2026-01-01T00:00:00"

    def test_noop_when_timestamp_is_none(self) -> None:
        row: dict[str, Any] = {
            "first_seen": "2026-01-01T00:00:00",
            "last_seen": "2026-01-01T00:00:00",
        }
        _touch_issue_timestamps(row, None)
        assert row["first_seen"] == "2026-01-01T00:00:00"


class TestNewIssueHistoryEntry:
    def test_creates_entry_with_github_url(self) -> None:
        entry = _new_issue_history_entry(42, "owner/repo")
        assert entry["issue_number"] == 42
        assert entry["issue_url"] == "https://github.com/owner/repo/issues/42"
        assert entry["title"] == "Issue #42"
        assert entry["status"] == "unknown"

    def test_creates_entry_with_empty_slug(self) -> None:
        entry = _new_issue_history_entry(1, "")
        assert entry["issue_url"] == ""

    def test_strips_github_https_prefix(self) -> None:
        entry = _new_issue_history_entry(5, "https://github.com/org/proj")
        assert entry["issue_url"] == "https://github.com/org/proj/issues/5"

    def test_strips_github_http_prefix(self) -> None:
        entry = _new_issue_history_entry(5, "http://github.com/org/proj")
        assert entry["issue_url"] == "https://github.com/org/proj/issues/5"


class TestBuildHistoryLinks:
    def test_converts_dict_entries(self) -> None:
        raw = {
            10: {"target_id": 10, "kind": "blocks", "target_url": "http://x"},
            20: {"target_id": 20, "kind": "relates_to"},
        }
        result = _build_history_links(raw)
        assert len(result) == 2
        assert result[0].target_id == 10
        assert result[0].kind == "blocks"
        assert result[1].target_id == 20

    def test_skips_zero_target_ids(self) -> None:
        raw = {0: {"target_id": 0, "kind": "blocks"}}
        result = _build_history_links(raw)
        assert result == []

    def test_handles_legacy_set_of_ints(self) -> None:
        raw = {5, 10}
        result = _build_history_links(raw)
        assert len(result) == 2
        ids = [lnk.target_id for lnk in result]
        assert 5 in ids
        assert 10 in ids


class TestBuildIssueHistoryEntry:
    def test_builds_entry_from_row(self) -> None:
        row = _new_issue_history_entry(7, "owner/repo")
        row["title"] = "Fix bug"
        row["status"] = "merged"
        entry = _build_issue_history_entry(row, None)
        assert entry.issue_number == 7
        assert entry.title == "Fix bug"
        assert entry.outcome is None


class TestAggregateTelemetryRecord:
    def test_aggregates_session_and_model(self) -> None:
        row = _new_issue_history_entry(1, "o/r")
        record: dict[str, Any] = {
            "timestamp": "2026-01-01T00:00:00",
            "session_id": "sess-1",
            "source": "planner",
            "model": "claude-4",
        }
        pr_to_issue: dict[int, int] = {}
        _aggregate_telemetry_record(row, record, pr_to_issue)
        assert "sess-1" in row["session_ids"]
        assert row["source_calls"]["planner"] == 1
        assert row["model_calls"]["claude-4"] == 1

    def test_accumulates_counters_when_enabled(self) -> None:
        row = _new_issue_history_entry(1, "o/r")
        record: dict[str, Any] = {
            "timestamp": "2026-01-01T00:00:00",
            "inference_calls": 5,
            "total_tokens": 100,
        }
        _aggregate_telemetry_record(row, record, {}, sum_counters=True)
        assert row["inference"]["inference_calls"] == 5
        assert row["inference"]["total_tokens"] == 100


class TestFilterRowsToItems:
    def test_filters_by_status(self) -> None:
        rows = {
            1: {**_new_issue_history_entry(1, "o/r"), "status": "merged"},
            2: {**_new_issue_history_entry(2, "o/r"), "status": "in_progress"},
        }
        mock_state = MagicMock()
        mock_state.get_outcome.return_value = None
        items = _filter_rows_to_items(rows, "merged", "", mock_state)
        assert len(items) == 1
        assert items[0].issue_number == 1

    def test_filters_by_query_text(self) -> None:
        rows = {
            1: {**_new_issue_history_entry(1, "o/r"), "title": "Fix login bug"},
            2: {**_new_issue_history_entry(2, "o/r"), "title": "Add feature"},
        }
        mock_state = MagicMock()
        mock_state.get_outcome.return_value = None
        items = _filter_rows_to_items(rows, "", "login", mock_state)
        assert len(items) == 1
        assert items[0].issue_number == 1

    def test_returns_all_without_filters(self) -> None:
        rows = {
            1: _new_issue_history_entry(1, "o/r"),
            2: _new_issue_history_entry(2, "o/r"),
        }
        mock_state = MagicMock()
        mock_state.get_outcome.return_value = None
        items = _filter_rows_to_items(rows, "", "", mock_state)
        assert len(items) == 2


class TestNormaliseSummaryLines:
    def test_strips_bullet_prefixes(self) -> None:
        raw = "- Line one\n- Line two\n- Line three"
        result = _normalise_summary_lines(raw)
        assert result == "Line one\nLine two\nLine three"

    def test_caps_at_8_lines(self) -> None:
        raw = "\n".join(f"Line {i}" for i in range(20))
        result = _normalise_summary_lines(raw)
        assert len(result.splitlines()) == 8

    def test_handles_empty_input(self) -> None:
        assert _normalise_summary_lines("") == ""


class TestBuildHitlContext:
    def test_builds_context_string(self) -> None:
        issue = MagicMock()
        issue.number = 42
        issue.title = "Fix timeout"
        issue.body = "The service times out"
        issue.comments = ["comment 1", "comment 2"]
        result = _build_hitl_context(issue, cause="CI failure", origin="review")
        assert "Issue #42: Fix timeout" in result
        assert "CI failure" in result
        assert "review" in result
        assert "comment 1" in result


class TestProcessEventsIntoRows:
    def test_processes_issue_created_event(self) -> None:
        event = MagicMock()
        event.timestamp = "2026-01-01T00:00:00"
        event.type = "issue_created"
        event.data = {
            "issue": 10,
            "title": "New issue",
            "url": "https://github.com/o/r/issues/10",
            "labels": [],
        }
        issue_rows: dict[int, dict[str, Any]] = {}
        pr_to_issue: dict[int, int] = {}
        _process_events_into_rows([event], issue_rows, pr_to_issue, None, None, "o/r")
        assert 10 in issue_rows
        assert issue_rows[10]["title"] == "New issue"
