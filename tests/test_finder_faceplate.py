"""Unit tests for the finder loop-faceplate pure join (#10826).

Fast, subprocess-free: exercises the read-only faceplate builder — calibrated
vs pending rows, status derivation (within / above / uncalibrated), null-safe
live rates, baseline staleness + unvouched-baseline low-confidence, and the
:class:`BaselineProvenance` / :class:`BaselineLedger` round-trip.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from finder_calibration import FinderFloor  # noqa: E402
from finder_faceplate import (  # noqa: E402
    FINDER_LOOP_WORKER,
    BaselineLedger,
    BaselineProvenance,
    baseline_ledger_path,
    build_faceplates,
    faceplate_row,
)

_NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)


def _floor(
    *,
    finder_id: str = "wiki_rot",
    mean: float = 1.0,
    sigma: float = 0.0,
    n: int = 3,
    threshold: int = 1,
    last_calibrated: datetime = _NOW,
) -> FinderFloor:
    return FinderFloor(
        finder_id=finder_id,
        floor_mean=mean,
        floor_sigma=sigma,
        sample_count=n,
        threshold=threshold,
        last_calibrated=last_calibrated,
    )


def _prov(
    *,
    finder_id: str = "wiki_rot",
    vetted_at: datetime | None = _NOW,
    signal_class: str = "wiki-rot",
) -> BaselineProvenance:
    return BaselineProvenance(
        finder_id=finder_id,
        sha="cafef00d",
        vetted_by="operator-supplied",
        signal_class=signal_class,
        vetted_at=vetted_at,
        note="clean for wiki-rot",
    )


# -- build_faceplates: one row per catalog finder ------------------------------


def test_empty_ledger_marks_every_finder_pending() -> None:
    rows = build_faceplates(floors={}, baselines={}, live_rates={}, now=_NOW)

    assert len(rows) == len(FINDER_LOOP_WORKER)
    assert {r["finder_id"] for r in rows} == set(FINDER_LOOP_WORKER)
    for row in rows:
        assert row["calibrated"] is False
        assert row["status"] == "uncalibrated"
        assert row["live_rate"] is None
        # Pending rows carry no floor fields.
        assert "floor_mean" not in row


def test_calibrated_finder_within_floor() -> None:
    rows = build_faceplates(
        floors={"wiki_rot": _floor(mean=1.0, sigma=0.0, threshold=1)},
        baselines={"wiki_rot": _prov()},
        live_rates={"wiki_rot": 1},
        now=_NOW,
    )
    row = next(r for r in rows if r["finder_id"] == "wiki_rot")

    assert row["calibrated"] is True
    assert row["status"] == "within_floor"
    assert row["live_rate"] == 1
    assert row["floor_mean"] == 1.0
    assert row["threshold"] == 1
    assert row["sample_count"] == 3
    assert row["low_confidence"] is False
    assert row["baseline_stale"] is False
    assert row["baseline_vetted"] is True
    assert row["baseline_sha"] == "cafef00d"


def test_calibrated_finder_above_floor() -> None:
    rows = build_faceplates(
        floors={"wiki_rot": _floor(mean=1.0, sigma=0.0, threshold=1)},
        baselines={"wiki_rot": _prov()},
        live_rates={"wiki_rot": 9},
        now=_NOW,
    )
    row = next(r for r in rows if r["finder_id"] == "wiki_rot")

    assert row["status"] == "above_floor"
    assert row["live_rate"] == 9


def test_calibrated_but_no_live_rate_is_within_floor_and_null_safe() -> None:
    rows = build_faceplates(
        floors={"wiki_rot": _floor()},
        baselines={"wiki_rot": _prov()},
        live_rates={"wiki_rot": None},
        now=_NOW,
    )
    row = next(r for r in rows if r["finder_id"] == "wiki_rot")

    # No observed live output ⇒ not exceeding the floor; live_rate stays null
    # rather than being invented as 0.
    assert row["status"] == "within_floor"
    assert row["live_rate"] is None


# -- baseline honesty ----------------------------------------------------------


def test_unvouched_baseline_flags_low_confidence_and_unknown_staleness() -> None:
    row = faceplate_row(
        finder_id="wiki_rot",
        signal_class="wiki-rot",
        floor=_floor(n=8),  # plenty of samples ⇒ floor itself is confident
        baseline=_prov(vetted_at=None),
        live_rate=1,
        now=_NOW,
    )

    assert row["baseline_vetted"] is False
    # An unvouched baseline miscalibrates silently ⇒ low_confidence regardless
    # of sample count, and staleness is unknown (null), never "fresh".
    assert row["low_confidence"] is True
    assert row["baseline_stale"] is None


def test_stale_vouched_baseline_is_flagged_stale() -> None:
    old = _NOW - timedelta(days=90)
    row = faceplate_row(
        finder_id="wiki_rot",
        signal_class="wiki-rot",
        floor=_floor(),
        baseline=_prov(vetted_at=old),
        live_rate=1,
        now=_NOW,
    )
    assert row["baseline_stale"] is True
    assert row["baseline_vetted"] is True


def test_drift_days_measures_time_since_calibration() -> None:
    row = faceplate_row(
        finder_id="wiki_rot",
        signal_class="wiki-rot",
        floor=_floor(last_calibrated=_NOW - timedelta(days=5)),
        baseline=_prov(),
        live_rate=0,
        now=_NOW,
    )
    assert row["drift_days"] == 5.0


def test_low_confidence_floor_flagged_even_with_vouched_baseline() -> None:
    row = faceplate_row(
        finder_id="wiki_rot",
        signal_class="wiki-rot",
        floor=_floor(n=1),  # below MIN_CONFIDENT_SAMPLES
        baseline=_prov(),
        live_rate=0,
        now=_NOW,
    )
    assert row["low_confidence"] is True


# -- provenance ledger round-trip ----------------------------------------------


def test_baseline_provenance_json_round_trip() -> None:
    prov = _prov(vetted_at=_NOW)
    restored = BaselineProvenance.from_json_dict(prov.to_json_dict())
    assert restored == prov

    unvouched = _prov(vetted_at=None)
    restored_unvouched = BaselineProvenance.from_json_dict(unvouched.to_json_dict())
    assert restored_unvouched.vetted_at is None
    assert restored_unvouched.vetted is False
    assert restored_unvouched.to_golden_baseline() is None


def test_baseline_ledger_latest_wins(tmp_path: Path) -> None:
    ledger = BaselineLedger(baseline_ledger_path(tmp_path))
    assert ledger.latest_by_finder() == {}  # missing file reads empty

    ledger.record(_prov(finder_id="wiki_rot", vetted_at=None))
    ledger.record(_prov(finder_id="wiki_rot", vetted_at=_NOW))
    ledger.record(_prov(finder_id="edge_proposer", vetted_at=_NOW))

    latest = ledger.latest_by_finder()
    assert set(latest) == {"wiki_rot", "edge_proposer"}
    # Append-only: the later wiki_rot row (vouched) supersedes the earlier one.
    assert latest["wiki_rot"].vetted is True
