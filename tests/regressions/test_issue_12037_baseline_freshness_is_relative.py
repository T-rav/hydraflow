"""#12037: a fixture that must read "fresh" ages into staleness and reddens CI.

`tests/test_diagnostics_finder_faceplates_route.py` pinned
`_NOW = datetime(2026, 8, 3, 12, 0, 0)` and recorded it as the baseline's
`vetted_at`. The route computes `baseline_stale` against the REAL clock —
`is_baseline_stale(golden, now)`, 30-day default — so the fixture was fresh for
thirty days and went stale at 2026-09-02T12:00Z, turning every PR in the repo
red for a reason no PR caused.

The immediate fix made that fixture now-relative. This pins the BEHAVIOUR in
both directions instead, expressed as ages rather than dates, so it cannot age
out: a baseline vetted just now reads fresh, and one vetted past the threshold
reads stale. A regression test written with a fixed date would be the same bug.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import config_mock

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from dashboard_routes._diagnostics_routes import build_diagnostics_router  # noqa: E402
from finder_calibration import (  # noqa: E402
    DEFAULT_MAX_BASELINE_AGE,
    CalibrationLedger,
    FinderFloor,
    calibration_ledger_path,
)
from finder_faceplate import (  # noqa: E402
    BaselineLedger,
    BaselineProvenance,
    baseline_ledger_path,
)

_FINDER = "wiki_rot"


def _faceplate(tmp_path: Path, *, age: timedelta) -> dict:
    """Record a baseline vetted *age* ago and read the route's verdict."""
    vetted_at = datetime.now(UTC) - age
    CalibrationLedger(calibration_ledger_path(tmp_path)).record(
        FinderFloor(
            finder_id=_FINDER,
            floor_mean=1.0,
            floor_sigma=0.0,
            sample_count=3,
            threshold=1,
            last_calibrated=vetted_at,
        )
    )
    BaselineLedger(baseline_ledger_path(tmp_path)).record(
        BaselineProvenance(
            finder_id=_FINDER,
            sha="cafef00d",
            vetted_by="operator-supplied",
            signal_class="wiki-rot",
            vetted_at=vetted_at,
        )
    )
    cfg = config_mock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    cfg.repo = "o/r"
    app = FastAPI()
    app.include_router(build_diagnostics_router(cfg))
    body = TestClient(app).get("/api/diagnostics/finder-faceplates").json()
    return {row["finder_id"]: row for row in body["finders"]}[_FINDER]


def test_a_baseline_vetted_now_is_not_stale(tmp_path: Path) -> None:
    """The property the original fixture was relying on, stated deliberately."""
    assert _faceplate(tmp_path, age=timedelta(0))["baseline_stale"] is False


def test_a_baseline_older_than_the_window_is_stale(tmp_path: Path) -> None:
    """The other direction — without it, a route that never flags stale passes."""
    aged = DEFAULT_MAX_BASELINE_AGE + timedelta(days=1)

    assert _faceplate(tmp_path, age=aged)["baseline_stale"] is True


@pytest.mark.parametrize(
    ("age", "stale"),
    [
        pytest.param(DEFAULT_MAX_BASELINE_AGE - timedelta(hours=1), False, id="inside"),
        pytest.param(DEFAULT_MAX_BASELINE_AGE + timedelta(hours=1), True, id="outside"),
    ],
)
def test_the_boundary_is_the_configured_window(
    tmp_path: Path, age: timedelta, stale: bool
) -> None:
    """Both sides of the threshold, read off the constant rather than hardcoded.

    Writing `30` here would re-create the original defect one level up: the test
    would keep passing while the window moved underneath it.
    """
    assert _faceplate(tmp_path, age=age)["baseline_stale"] is stale
