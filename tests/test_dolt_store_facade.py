"""Tests for DoltStore facade methods — review records, harness failures, retrospectives, events."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path):  # noqa: ANN201
    """Create a DoltStore with a mocked DoltConnection."""
    from dolt.store import DoltStore

    with patch("dolt.store.DoltConnection") as MockConn:
        mock_db = MagicMock()
        MockConn.return_value = mock_db
        store = DoltStore(dolt_dir=tmp_path)
        store.db = mock_db
        return store


# ---------------------------------------------------------------------------
# Review records
# ---------------------------------------------------------------------------


class TestAppendReviewRecord:
    def test_append_delegates_to_repository(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        record = {"issue_number": 42, "result": "approved"}
        store._review_records = MagicMock()
        store.append_review_record(record)
        store._review_records.append.assert_called_once_with(record)

    def test_load_recent_review_records(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._review_records = MagicMock()
        store._review_records.query.return_value = [
            {"record": {"issue_number": 1}},
            {"record": {"issue_number": 2}},
        ]
        result = store.load_recent_review_records(10)
        assert len(result) == 2
        assert result[0] == {"issue_number": 1}


# ---------------------------------------------------------------------------
# Harness failures
# ---------------------------------------------------------------------------


class TestAppendHarnessFailure:
    def test_append_delegates_to_repository(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        failure = {"category": "ci_failure", "issue_number": 5}
        store._harness_failures = MagicMock()
        store.append_harness_failure(failure)
        store._harness_failures.append.assert_called_once_with(failure)

    def test_load_recent_harness_failures(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._harness_failures = MagicMock()
        store._harness_failures.query.return_value = [
            {"failure": {"category": "ci_failure"}},
        ]
        result = store.load_recent_harness_failures(5)
        assert len(result) == 1
        assert result[0] == {"category": "ci_failure"}


# ---------------------------------------------------------------------------
# Retrospectives
# ---------------------------------------------------------------------------


class TestAppendRetrospective:
    def test_append_delegates_to_repository(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        retro = {"issue_number": 10, "quality_fix_rate": 0.8}
        store._retrospectives = MagicMock()
        store.append_retrospective(retro)
        store._retrospectives.append.assert_called_once_with(retro)

    def test_load_recent_retrospectives(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._retrospectives = MagicMock()
        store._retrospectives.query.return_value = [
            {"retrospective": {"issue_number": 10}},
        ]
        result = store.load_recent_retrospectives(5)
        assert len(result) == 1
        assert result[0] == {"issue_number": 10}


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestAppendEvent:
    def test_append_extracts_type_and_delegates(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._events = MagicMock()
        event = {"type": "phase_change", "data": {"issue": 1}}
        store.append_event(event)
        store._events.append.assert_called_once_with("phase_change", event)

    def test_append_event_missing_type_uses_unknown(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._events = MagicMock()
        event = {"data": {"x": 1}}
        store.append_event(event)
        store._events.append.assert_called_once_with("unknown", event)


class TestLoadRecentEvents:
    def test_load_returns_payloads(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._events = MagicMock()
        store._events.query.return_value = [
            {"payload": {"type": "error", "data": {}}},
        ]
        result = store.load_recent_events(10)
        assert len(result) == 1
        assert result[0] == {"type": "error", "data": {}}


class TestLoadEventsSince:
    def test_load_events_since_delegates(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._events = MagicMock()
        store._events.query_since.return_value = [
            {"payload": {"type": "phase_change"}},
        ]
        result = store.load_events_since("2024-01-01T00:00:00")
        store._events.query_since.assert_called_once_with("2024-01-01T00:00:00")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Metrics snapshots
# ---------------------------------------------------------------------------


class TestRecordMetricsSnapshot:
    def test_delegates_to_repository(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._metrics_snap = MagicMock()
        snapshot = {"timestamp": "2024-01-01", "data": {"issues": 5}}
        store.record_metrics_snapshot(snapshot)
        store._metrics_snap.append.assert_called_once_with(snapshot)


class TestGetMetricsHistory:
    def test_returns_snapshots(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._metrics_snap = MagicMock()
        store._metrics_snap.query.return_value = [
            {"snapshot": {"issues": 5}},
            {"snapshot": {"issues": 10}},
        ]
        result = store.get_metrics_history(10)
        assert len(result) == 2
        assert result[0] == {"issues": 5}


# ---------------------------------------------------------------------------
# set_memory_state alias
# ---------------------------------------------------------------------------


class TestSetMemoryState:
    def test_delegates_to_update_memory_state(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store._memory_state = MagicMock()
        store.set_memory_state([1, 2, 3], "abc123")
        # set_memory_state calls update_memory_state which calls _memory_state.update
        store._memory_state.update.assert_called_once()


# ---------------------------------------------------------------------------
# Proposed categories
# ---------------------------------------------------------------------------


class TestProposedCategories:
    def test_get_proposed_categories(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.db.fetchall.return_value = [("ci_failure",), ("lint_error",)]
        result = store.get_proposed_categories("harness")
        assert result == {"ci_failure", "lint_error"}

    def test_mark_category_proposed(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.mark_category_proposed("harness", "ci_failure")
        store.db.execute.assert_called_once()
