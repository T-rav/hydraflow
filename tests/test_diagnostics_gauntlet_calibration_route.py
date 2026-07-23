"""Test for the /api/diagnostics/gauntlet-calibration panel endpoint (#10371)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import judge_independence as ji  # noqa: E402
from dashboard_routes._diagnostics_routes import build_diagnostics_router  # noqa: E402


def test_gauntlet_calibration_panel_reports_ledger_metrics(tmp_path: Path) -> None:
    config = MagicMock()
    config.data_root = tmp_path
    config.diagnostics_dir = tmp_path / "diagnostics"

    ledger = ji.ledger_path_for(config)
    classes = frozenset({ji.BlastRadiusClass.STRUCTURAL})
    ji.record_classed_verdict(
        ledger,
        lens=None,
        pr=1,
        surface="pr_review",
        classes=classes,
        independent=True,
        judge_family="openai",
        verdict="VETO",
        dissent=True,
    )
    ji.record_fail_open(
        ledger,
        lens="security",
        pr=2,
        surface="pr_review",
        classes=classes,
        disposition=ji.FailOpenDisposition.FAIL_OPEN_LEDGERED,
        reason="boom",
    )

    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    client = TestClient(app)

    resp = client.get("/api/diagnostics/gauntlet-calibration")
    assert resp.status_code == 200
    data = resp.json()
    assert data["classed_verdicts"] == 1
    assert data["independent_verdicts"] == 1
    assert data["pct_independent"] == 100.0
    assert data["fail_open_total"] == 1
    assert data["disagreement_by_family"]["openai"] == {"verdicts": 1, "dissents": 1}


def test_gauntlet_calibration_panel_empty_ledger(tmp_path: Path) -> None:
    config = MagicMock()
    config.data_root = tmp_path
    config.diagnostics_dir = tmp_path / "diagnostics"

    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    client = TestClient(app)

    resp = client.get("/api/diagnostics/gauntlet-calibration")
    assert resp.status_code == 200
    assert resp.json()["classed_verdicts"] == 0
