"""Tests for GET /api/diagnostics/judge-calibration (#10836).

Read-only proper-scoring panel: an empty verdict ledger yields no judges (never
a 500); a seeded verdict ledger + escape ledger resolves per-judge scores across
the two axes; a too-recent verdict is unresolved; an escape-ledger read failure
degrades to "no outcomes" rather than erroring.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dashboard_routes._diagnostics_routes import build_diagnostics_router  # noqa: E402
from escape.ledger import ESCAPE_LEDGER_FILENAME, EscapeLedger  # noqa: E402
from escape.models import EscapeRecord  # noqa: E402
from judge_calibration import (  # noqa: E402
    JudgeCalibrationLedger,
    JudgeVerdictRecord,
    Verdict,
    judge_verdict_ledger_path,
)

# _NOW anchors every fixture timestamp and MUST be wall-clock-relative: the
# route resolves outcomes against the real ``datetime.now(UTC)``, so a frozen
# anchor silently ages past the 7-day grace window and flips "too recent →
# unresolved" fixtures into resolved ones (armed 2026-08-10 when the original
# ``datetime(2026, 8, 3)`` constant crossed the window; the same time-bomb
# class as #11045 / find #11047). The engine tests may keep a frozen anchor —
# they pass ``now=_NOW`` explicitly, so their clock is self-consistent.
_NOW = datetime.now(UTC)


def _config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.diagnostics_dir = tmp_path / "diagnostics"
    cfg.repo = "o/r"
    return cfg


def _client(cfg: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(build_diagnostics_router(cfg))
    return TestClient(app)


def _record_verdict(
    tmp_path: Path,
    subject: str,
    verdict: Verdict,
    confidence: float,
    *,
    judge: str = "post_verify",
    at: datetime = _NOW,
) -> None:
    JudgeCalibrationLedger(judge_verdict_ledger_path(tmp_path)).record(
        JudgeVerdictRecord(
            judge_id=judge,
            judge_family="review_advisor",
            subject_id=subject,
            verdict=verdict,
            confidence=confidence,
            recorded_at=at,
        )
    )


def _record_escape(tmp_path: Path, originating_pr: int) -> None:
    EscapeLedger(tmp_path / "diagnostics" / ESCAPE_LEDGER_FILENAME).append(
        EscapeRecord(
            id=f"revert:sha{originating_pr}",
            detected_at=_NOW.isoformat(),
            detection_source="revert",
            detection_ref=f"sha{originating_pr}",
            originating_pr=originating_pr,
            originating_merge_sha=f"merge{originating_pr}",
            merged_at=(_NOW - timedelta(days=10)).isoformat(),
            time_to_detection_hours=1.0,
            attribution_method="revert-parse",
            attribution_confidence="high",
            encoded_as="none-yet",
            notes="",
        )
    )


def test_empty_ledger_returns_no_judges(tmp_path: Path) -> None:
    resp = _client(_config(tmp_path)).get("/api/diagnostics/judge-calibration")
    assert resp.status_code == 200
    body = resp.json()
    assert body["judges"] == []
    assert body["resolved_total"] == 0
    assert body["grace_window_days"] == 7


def test_seeded_ledger_scores_both_axes(tmp_path: Path) -> None:
    # A good change passed with high confidence (past grace, escape-free) and a
    # bad change vetoed with high confidence (escape attributed) → the judge
    # discriminates perfectly and is well calibrated.
    old = _NOW - timedelta(days=10)
    _record_verdict(tmp_path, "pr:1", Verdict.PASS, 0.9, at=old)  # → good
    _record_verdict(tmp_path, "pr:2", Verdict.FAIL, 0.9, at=old)  # → bad (escape)
    _record_escape(tmp_path, originating_pr=2)

    resp = _client(_config(tmp_path)).get("/api/diagnostics/judge-calibration")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_total"] == 2
    rows = {r["judge_id"]: r for r in body["judges"]}
    row = rows["post_verify"]
    assert row["judge_family"] == "review_advisor"
    assert row["n_resolved"] == 2
    # PASS@0.9 on a good and FAIL@0.9 on a bad → predicted 0.9/0.1, both correct.
    assert row["brier"] < 0.02
    assert row["discrimination"] == 1.0
    assert row["discrimination_undefined"] is False
    assert row["calibration_bins"]  # non-empty reliability curve


def test_too_recent_verdict_is_unresolved(tmp_path: Path) -> None:
    # Verdict recorded now (inside the grace window), no escape → no outcome yet.
    _record_verdict(tmp_path, "pr:5", Verdict.PASS, 0.8, at=_NOW)

    resp = _client(_config(tmp_path)).get("/api/diagnostics/judge-calibration")
    body = resp.json()
    assert body["resolved_total"] == 0
    row = {r["judge_id"]: r for r in body["judges"]}["post_verify"]
    assert row["n_resolved"] == 0
    assert row["brier"] is None
    assert row["low_confidence"] is True


def test_escape_read_failure_is_soft(tmp_path: Path) -> None:
    _record_verdict(tmp_path, "pr:1", Verdict.PASS, 0.9, at=_NOW - timedelta(days=10))

    with patch.object(EscapeLedger, "read_latest", side_effect=OSError("boom")):
        resp = _client(_config(tmp_path)).get("/api/diagnostics/judge-calibration")

    # A read failure degrades to no outcomes (judge present, unresolved), not 500.
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_total"] == 0
    assert {r["judge_id"] for r in body["judges"]} == {"post_verify"}
