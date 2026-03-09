"""Tests for dolt repository classes — verify SQL queries match schema."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from dolt.insights import (
    CuratedManifestRepository,
    HarnessFailureRepository,
    RetrospectiveRepository,
    ReviewRecordRepository,
)
from dolt.learnings import LearningRepository
from dolt.persistence import (
    ContextCacheRepository,
    EventRepository,
    MetricsSnapshotRepository,
    RunRepository,
    SessionRepository,
)
from dolt.telemetry import ModelPricingRepository
from dolt.troubleshooting import TroubleshootingPatternRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db() -> MagicMock:
    """Return a mock DoltConnection."""
    db = MagicMock()
    db.fetchone.return_value = None
    db.fetchall.return_value = []
    return db


# ---------------------------------------------------------------------------
# ReviewRecordRepository
# ---------------------------------------------------------------------------


class TestReviewRecordRepository:
    def test_append_uses_data_json_column(self) -> None:
        db = _mock_db()
        repo = ReviewRecordRepository(db)
        repo.append({"issue": 1, "verdict": "approved"})
        sql = db.execute.call_args[0][0]
        assert "data_json" in sql
        assert "record_json" not in sql

    def test_query_uses_data_json_and_timestamp(self) -> None:
        db = _mock_db()
        repo = ReviewRecordRepository(db)
        repo.query(10)
        sql = db.fetchall.call_args[0][0]
        assert "data_json" in sql
        assert "timestamp" in sql
        assert "created_at" not in sql

    def test_query_parses_json_rows(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            (1, json.dumps({"issue": 42}), "2024-01-01"),
        ]
        repo = ReviewRecordRepository(db)
        result = repo.query(10)
        assert len(result) == 1
        assert result[0]["record"]["issue"] == 42


# ---------------------------------------------------------------------------
# HarnessFailureRepository
# ---------------------------------------------------------------------------


class TestHarnessFailureRepository:
    def test_append_uses_data_json_column(self) -> None:
        db = _mock_db()
        repo = HarnessFailureRepository(db)
        repo.append({"category": "ci_failure"})
        sql = db.execute.call_args[0][0]
        assert "data_json" in sql
        assert "failure_json" not in sql

    def test_query_uses_data_json_and_timestamp(self) -> None:
        db = _mock_db()
        repo = HarnessFailureRepository(db)
        repo.query(10)
        sql = db.fetchall.call_args[0][0]
        assert "data_json" in sql
        assert "timestamp" in sql

    def test_query_parses_json_rows(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            (1, json.dumps({"category": "ci_failure"}), "2024-01-01"),
        ]
        repo = HarnessFailureRepository(db)
        result = repo.query(10)
        assert result[0]["failure"]["category"] == "ci_failure"


# ---------------------------------------------------------------------------
# RetrospectiveRepository
# ---------------------------------------------------------------------------


class TestRetrospectiveRepository:
    def test_append_uses_data_json_column(self) -> None:
        db = _mock_db()
        repo = RetrospectiveRepository(db)
        repo.append({"issue_number": 1})
        sql = db.execute.call_args[0][0]
        assert "data_json" in sql
        assert "retrospective_json" not in sql

    def test_query_uses_data_json_and_timestamp(self) -> None:
        db = _mock_db()
        repo = RetrospectiveRepository(db)
        repo.query(10)
        sql = db.fetchall.call_args[0][0]
        assert "data_json" in sql
        assert "timestamp" in sql

    def test_query_parses_json_rows(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            (1, json.dumps({"issue_number": 5}), "2024-01-01"),
        ]
        repo = RetrospectiveRepository(db)
        result = repo.query(10)
        assert result[0]["retrospective"]["issue_number"] == 5


# ---------------------------------------------------------------------------
# CuratedManifestRepository
# ---------------------------------------------------------------------------


class TestCuratedManifestRepository:
    def test_upsert_uses_correct_columns(self) -> None:
        db = _mock_db()
        repo = CuratedManifestRepository(db)
        repo.upsert("src/main.py", {"type": "module"})
        sql = db.execute.call_args[0][0]
        assert "manifest_key" in sql
        assert "entry_json" in sql

    def test_get_returns_parsed_json(self) -> None:
        db = _mock_db()
        db.fetchone.return_value = (json.dumps({"type": "module"}),)
        repo = CuratedManifestRepository(db)
        result = repo.get("src/main.py")
        assert result == {"type": "module"}

    def test_get_returns_none_when_missing(self) -> None:
        db = _mock_db()
        repo = CuratedManifestRepository(db)
        assert repo.get("nope") is None

    def test_get_all_returns_dict(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            ("src/a.py", json.dumps({"t": "mod"})),
            ("src/b.py", json.dumps({"t": "test"})),
        ]
        repo = CuratedManifestRepository(db)
        result = repo.get_all()
        assert len(result) == 2
        assert result["src/a.py"]["t"] == "mod"

    def test_delete(self) -> None:
        db = _mock_db()
        repo = CuratedManifestRepository(db)
        repo.delete("src/a.py")
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# EventRepository
# ---------------------------------------------------------------------------


class TestEventRepository:
    def test_append_uses_data_json_column(self) -> None:
        db = _mock_db()
        repo = EventRepository(db)
        repo.append("phase_change", {"phase": "plan"})
        sql = db.execute.call_args[0][0]
        assert "data_json" in sql
        assert "payload_json" not in sql

    def test_query_without_filter(self) -> None:
        db = _mock_db()
        repo = EventRepository(db)
        repo.query(limit=10)
        sql = db.fetchall.call_args[0][0]
        assert "data_json" in sql
        assert "WHERE" not in sql

    def test_query_with_type_filter(self) -> None:
        db = _mock_db()
        repo = EventRepository(db)
        repo.query(event_type="error", limit=10)
        sql = db.fetchall.call_args[0][0]
        assert "WHERE event_type" in sql

    def test_query_parses_json(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            (1, "error", json.dumps({"msg": "fail"}), "2024-01-01"),
        ]
        repo = EventRepository(db)
        result = repo.query(limit=1)
        assert result[0]["payload"]["msg"] == "fail"

    def test_query_since(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            (5, "phase_change", json.dumps({"x": 1}), "2024-01-02"),
        ]
        repo = EventRepository(db)
        result = repo.query_since("2024-01-01T00:00:00")
        sql = db.fetchall.call_args[0][0]
        assert "timestamp >=" in sql
        assert len(result) == 1


# ---------------------------------------------------------------------------
# RunRepository
# ---------------------------------------------------------------------------


class TestRunRepository:
    def test_create(self) -> None:
        db = _mock_db()
        repo = RunRepository(db)
        repo.create("run-1", {"issue": 42})
        db.execute.assert_called_once()

    def test_get_returns_parsed(self) -> None:
        db = _mock_db()
        db.fetchone.return_value = (json.dumps({"issue": 42}),)
        repo = RunRepository(db)
        result = repo.get("run-1")
        assert result == {"issue": 42}

    def test_get_returns_none_when_missing(self) -> None:
        db = _mock_db()
        repo = RunRepository(db)
        assert repo.get("nope") is None

    def test_delete(self) -> None:
        db = _mock_db()
        repo = RunRepository(db)
        repo.delete("run-1")
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# SessionRepository
# ---------------------------------------------------------------------------


class TestSessionRepository:
    def test_create(self) -> None:
        db = _mock_db()
        repo = SessionRepository(db)
        repo.create("sess-1", {"start": "now"})
        db.execute.assert_called_once()

    def test_get_returns_parsed(self) -> None:
        db = _mock_db()
        db.fetchone.return_value = (json.dumps({"start": "now"}),)
        repo = SessionRepository(db)
        assert repo.get("sess-1") == {"start": "now"}


# ---------------------------------------------------------------------------
# ContextCacheRepository
# ---------------------------------------------------------------------------


class TestContextCacheRepository:
    def test_get_returns_value(self) -> None:
        db = _mock_db()
        db.fetchone.return_value = ("cached_value",)
        repo = ContextCacheRepository(db)
        assert repo.get("key1") == "cached_value"

    def test_get_returns_none_when_missing(self) -> None:
        db = _mock_db()
        repo = ContextCacheRepository(db)
        assert repo.get("nope") is None

    def test_set_uses_replace(self) -> None:
        db = _mock_db()
        repo = ContextCacheRepository(db)
        repo.set("key1", "val1")
        sql = db.execute.call_args[0][0]
        assert "REPLACE" in sql

    def test_get_all(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [("k1", "v1"), ("k2", "v2")]
        repo = ContextCacheRepository(db)
        result = repo.get_all()
        assert result == {"k1": "v1", "k2": "v2"}


# ---------------------------------------------------------------------------
# MetricsSnapshotRepository
# ---------------------------------------------------------------------------


class TestMetricsSnapshotRepository:
    def test_append(self) -> None:
        db = _mock_db()
        repo = MetricsSnapshotRepository(db)
        repo.append({"issues": 5})
        sql = db.execute.call_args[0][0]
        assert "snapshot_json" in sql

    def test_query_parses_json(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            (1, json.dumps({"issues": 5}), "2024-01-01"),
        ]
        repo = MetricsSnapshotRepository(db)
        result = repo.query(10)
        assert result[0]["snapshot"]["issues"] == 5


# ---------------------------------------------------------------------------
# LearningRepository
# ---------------------------------------------------------------------------


class TestLearningRepository:
    def test_append_uses_data_json_column(self) -> None:
        db = _mock_db()
        repo = LearningRepository(db)
        repo.append({"lesson": "always test"})
        sql = db.execute.call_args[0][0]
        assert "data_json" in sql
        assert "learning_json" not in sql

    def test_query_uses_data_json_and_timestamp(self) -> None:
        db = _mock_db()
        repo = LearningRepository(db)
        repo.query(10)
        sql = db.fetchall.call_args[0][0]
        assert "data_json" in sql
        assert "timestamp" in sql
        assert "created_at" not in sql

    def test_query_parses_json(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            (1, json.dumps({"lesson": "test"}), "2024-01-01"),
        ]
        repo = LearningRepository(db)
        result = repo.query(10)
        assert result[0]["learning"]["lesson"] == "test"


# ---------------------------------------------------------------------------
# ModelPricingRepository
# ---------------------------------------------------------------------------


class TestModelPricingRepository:
    def test_upsert_uses_model_id_column(self) -> None:
        db = _mock_db()
        repo = ModelPricingRepository(db)
        repo.upsert("claude-3", {"input_cost_per_million": 3.0, "output_cost_per_million": 15.0})
        sql = db.execute.call_args[0][0]
        assert "model_id" in sql
        assert "model_name" not in sql
        assert "pricing_json" not in sql

    def test_get_uses_model_id(self) -> None:
        db = _mock_db()
        db.fetchone.return_value = ("claude-3", 3.0, 15.0, 0, 0, "[]")
        repo = ModelPricingRepository(db)
        result = repo.get("claude-3")
        assert result is not None
        assert result["model_id"] == "claude-3"
        assert result["input_cost_per_million"] == 3.0

    def test_get_returns_none_when_missing(self) -> None:
        db = _mock_db()
        repo = ModelPricingRepository(db)
        assert repo.get("nope") is None

    def test_get_all_returns_dict_by_model_id(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            ("claude-3", 3.0, 15.0, 0.5, 0.1, json.dumps(["claude-3-opus"])),
        ]
        repo = ModelPricingRepository(db)
        result = repo.get_all()
        assert "claude-3" in result
        assert result["claude-3"]["aliases"] == ["claude-3-opus"]

    def test_delete_uses_model_id(self) -> None:
        db = _mock_db()
        repo = ModelPricingRepository(db)
        repo.delete("claude-3")
        sql = db.execute.call_args[0][0]
        assert "model_id" in sql


# ---------------------------------------------------------------------------
# TroubleshootingPatternRepository
# ---------------------------------------------------------------------------


class TestTroubleshootingPatternRepository:
    def test_upsert_uses_language_and_pattern_name(self) -> None:
        db = _mock_db()
        repo = TroubleshootingPatternRepository(db)
        repo.upsert("python:import_error", {"fix": "check imports", "frequency": 3})
        sql = db.execute.call_args[0][0]
        assert "language" in sql
        assert "pattern_name" in sql
        assert "data_json" in sql
        assert "pattern_key" not in sql

    def test_upsert_splits_key_correctly(self) -> None:
        db = _mock_db()
        repo = TroubleshootingPatternRepository(db)
        repo.upsert("python:import_error", {"frequency": 1})
        params = db.execute.call_args[0][1]
        assert params[0] == "python"
        assert params[1] == "import_error"

    def test_get_queries_by_language_and_name(self) -> None:
        db = _mock_db()
        db.fetchone.return_value = (json.dumps({"fix": "check"}),)
        repo = TroubleshootingPatternRepository(db)
        result = repo.get("python:import_error")
        assert result == {"fix": "check"}

    def test_get_all_returns_keyed_dict(self) -> None:
        db = _mock_db()
        db.fetchall.return_value = [
            ("python", "import_error", json.dumps({"fix": "check"})),
        ]
        repo = TroubleshootingPatternRepository(db)
        result = repo.get_all()
        assert "python:import_error" in result

    def test_delete_uses_language_and_name(self) -> None:
        db = _mock_db()
        repo = TroubleshootingPatternRepository(db)
        repo.delete("python:import_error")
        sql = db.execute.call_args[0][0]
        assert "language" in sql
        assert "pattern_name" in sql

    def test_query_orders_by_frequency(self) -> None:
        db = _mock_db()
        repo = TroubleshootingPatternRepository(db)
        repo.query(10)
        sql = db.fetchall.call_args[0][0]
        assert "frequency DESC" in sql

    def test_split_key_no_colon(self) -> None:
        lang, name = TroubleshootingPatternRepository._split_key("simple")
        assert lang == ""
        assert name == "simple"

    def test_split_key_with_colon(self) -> None:
        lang, name = TroubleshootingPatternRepository._split_key("py:err")
        assert lang == "py"
        assert name == "err"
