"""Finder loop-faceplate join — pure read-only panel builder (#10826).

The finder-calibration engine (:mod:`finder_calibration`, #10821) measures each
generative finder's noise floor against a golden baseline and persists it to the
:class:`~finder_calibration.CalibrationLedger`. That answers "what does this
finder flag on a known-clean tree?" — its sensor noise. This module answers the
operator-facing question the faceplate panel poses: **is a finder's LIVE output
distinguishable from that noise, or is it firing on its own floor?**

It is the read-only JOIN half of the slice: it consumes

* the latest :class:`~finder_calibration.FinderFloor` per finder (the measured
  floor + actuation threshold),
* the baseline provenance that floor was measured against
  (:class:`BaselineProvenance` — which sha, whether an operator vouched it
  clean), and
* a per-finder live finding-rate (the recent count of findings the finder's
  loop filed, sourced by the caller from the per-loop event rollup),

and renders one honest faceplate row per finder. Nothing here runs a finder,
measures a floor, or files anything — the calibration script owns that. An empty
ledger yields every finder ``calibrated: false`` (the panel shows "pending"),
never an error.

Honesty rules carried through the join (they mirror the engine's, #10821):

* A floor backed by too few samples is ``low_confidence`` — the engine's own
  ``FinderFloor.low_confidence`` gate.
* A baseline no operator has vouched clean (``vetted_at is None``) is surfaced
  as ``baseline_vetted: false`` and folds into ``low_confidence`` — an unvouched
  "clean" tree miscalibrates silently, so the panel must not pretend it is
  trustworthy. ``baseline_stale`` is only computed when there IS a vouched
  ``vetted_at`` to age; otherwise it is ``null`` (unknown, not "fresh").
* A finder with no recorded live-count source yields ``live_rate: null`` and a
  status derived from calibration alone — the count is never invented.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from finder_calibration import (
    CALIBRATION_SUBDIR,
    GENERATIVE_FINDERS,
    FinderFloor,
    GoldenBaseline,
    drift_since,
    indistinguishable_from_floor,
    is_baseline_stale,
)
from jsonl_ledger import AppendOnlyJsonlLedger

logger = logging.getLogger(__name__)

#: Baseline-provenance sidecar filename, alongside the floor ledger under
#: ``<data_root>/calibration/``.
BASELINES_FILENAME = "finder_baselines.jsonl"

#: ``finder_id`` -> the background loop ``worker_name`` whose filed-findings
#: count is that finder's live output. The floor ledger keys on ``finder_id``
#: (finder_calibration's catalog); the per-loop event rollup keys on
#: ``worker_name`` — this bridges the two so the join can attach a live rate.
#: Every catalog finder maps to exactly one loop.
FINDER_LOOP_WORKER: dict[str, str] = {
    "erosion_metrics": "erosion_metrics",
    "edge_proposer": "edge_proposer",
    "entry_evidence": "entry_evidence",
    "term_proposer": "term_proposer",
    "wiki_rot": "wiki_rot_detector",
}

#: The three faceplate statuses (single source so the endpoint + tests agree).
STATUS_WITHIN_FLOOR = "within_floor"
STATUS_ABOVE_FLOOR = "above_floor"
STATUS_UNCALIBRATED = "uncalibrated"


@dataclass(frozen=True)
class BaselineProvenance:
    """The golden baseline one finder's floor was measured against (#10826).

    The floor ledger (:class:`~finder_calibration.FinderFloor`) records the
    measured statistics but NOT which sha they were measured against, nor whether
    an operator vouched that sha clean. Calibration is only trustworthy if that
    provenance is recorded honestly, so the calibrator writes one of these per
    finder alongside each floor.

    ``vetted_at`` is deliberately optional: ``None`` means the operator supplied
    the sha but could not (yet) vouch it defect-free for this signal class. That
    is a first-class low-confidence signal — surfaced downstream, never papered
    over as if the tree were vetted.
    """

    finder_id: str
    sha: str
    vetted_by: str
    signal_class: str
    vetted_at: datetime | None = None
    note: str = ""

    @property
    def vetted(self) -> bool:
        """True only when an operator vouched a concrete ``vetted_at``."""
        return self.vetted_at is not None

    def to_golden_baseline(self) -> GoldenBaseline | None:
        """Reconstruct the engine's :class:`GoldenBaseline`, or ``None``.

        Returns ``None`` for an unvouched baseline (``vetted_at is None``) —
        :func:`~finder_calibration.is_baseline_stale` ages ``vetted_at`` and a
        missing one has no age, so the caller treats staleness as unknown.
        """
        if self.vetted_at is None:
            return None
        return GoldenBaseline(
            sha=self.sha,
            vetted_at=self.vetted_at,
            vetted_by=self.vetted_by,
            signal_class=self.signal_class,
            note=self.note,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "finder_id": self.finder_id,
            "sha": self.sha,
            "vetted_by": self.vetted_by,
            "signal_class": self.signal_class,
            "vetted_at": self.vetted_at.isoformat() if self.vetted_at else None,
            "note": self.note,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> BaselineProvenance:
        raw_vetted = raw.get("vetted_at")
        vetted_at = (
            datetime.fromisoformat(str(raw_vetted))
            if isinstance(raw_vetted, str) and raw_vetted
            else None
        )
        return cls(
            finder_id=str(raw["finder_id"]),
            sha=str(raw.get("sha", "")),
            vetted_by=str(raw.get("vetted_by", "")),
            signal_class=str(raw.get("signal_class", "")),
            vetted_at=vetted_at,
            note=str(raw.get("note", "")),
        )


def baseline_ledger_path(data_root: Path) -> Path:
    """Return ``<data_root>/calibration/finder_baselines.jsonl``."""
    return data_root / CALIBRATION_SUBDIR / BASELINES_FILENAME


class BaselineLedger:
    """Append-only per-finder baseline-provenance sidecar (last write wins).

    Mirrors :class:`~finder_calibration.CalibrationLedger`: one JSONL row per
    calibration, latest row per ``finder_id`` supersedes earlier ones. Tolerates
    a missing file (reads as empty).
    """

    def __init__(self, path: Path) -> None:
        self._ledger: AppendOnlyJsonlLedger[BaselineProvenance] = AppendOnlyJsonlLedger(
            path, BaselineProvenance, logger=logger
        )

    @property
    def path(self) -> Path:
        return self._ledger.path

    def record(self, provenance: BaselineProvenance) -> None:
        self._ledger.append(provenance)

    def latest_by_finder(self) -> dict[str, BaselineProvenance]:
        index: dict[str, BaselineProvenance] = {}
        for row in self._ledger.read_all():
            index[row.finder_id] = row
        return index


def _status(floor: FinderFloor | None, live_rate: int | None) -> str:
    """Derive the faceplate status from the floor + live rate.

    * No floor ⇒ ``uncalibrated``.
    * A floor but no live count ⇒ ``within_floor``: with no observed live output
      the finder is by definition not exceeding its floor (documented; the count
      is not invented, ``live_rate`` stays ``null`` in the row).
    * A floor + a live count ⇒ the engine's own control-limit test.
    """
    if floor is None:
        return STATUS_UNCALIBRATED
    if live_rate is None:
        return STATUS_WITHIN_FLOOR
    within = indistinguishable_from_floor(
        live_rate, floor.floor_mean, floor.floor_sigma
    )
    return STATUS_WITHIN_FLOOR if within else STATUS_ABOVE_FLOOR


def faceplate_row(
    *,
    finder_id: str,
    signal_class: str,
    floor: FinderFloor | None,
    baseline: BaselineProvenance | None,
    live_rate: int | None,
    now: datetime,
) -> dict[str, Any]:
    """Build one finder's faceplate row. Pure; never raises on missing data."""
    row: dict[str, Any] = {
        "finder_id": finder_id,
        "signal_class": signal_class,
        "calibrated": floor is not None,
        "live_rate": live_rate,
        "status": _status(floor, live_rate),
    }
    if floor is None:
        return row

    golden = baseline.to_golden_baseline() if baseline is not None else None
    baseline_stale: bool | None = (
        is_baseline_stale(golden, now) if golden is not None else None
    )
    baseline_vetted = baseline is not None and baseline.vetted
    # An unvouched baseline miscalibrates silently — fold it into low_confidence
    # alongside the engine's own too-few-samples gate.
    low_confidence = floor.low_confidence or (
        baseline is not None and not baseline_vetted
    )

    row.update(
        {
            "floor_mean": floor.floor_mean,
            "floor_sigma": floor.floor_sigma,
            "threshold": floor.threshold,
            "sample_count": floor.sample_count,
            "low_confidence": low_confidence,
            "last_calibrated": floor.last_calibrated.isoformat(),
            "drift_days": round(drift_since(floor, now).total_seconds() / 86400.0, 2),
            "baseline_stale": baseline_stale,
            "baseline_sha": baseline.sha if baseline is not None else None,
            "baseline_vetted": baseline_vetted,
        }
    )
    return row


def build_faceplates(
    floors: dict[str, FinderFloor],
    baselines: dict[str, BaselineProvenance],
    live_rates: dict[str, int | None],
    now: datetime,
) -> list[dict[str, Any]]:
    """Render one faceplate row per catalog finder, in catalog order.

    Pure over its inputs. Every :data:`~finder_calibration.GENERATIVE_FINDERS`
    entry gets a row whether or not it has been calibrated — an uncalibrated
    finder shows as ``calibrated: false`` ("pending") rather than being omitted,
    so the panel enumerates the full fleet.
    """
    return [
        faceplate_row(
            finder_id=finder.finder_id,
            signal_class=finder.signal_class,
            floor=floors.get(finder.finder_id),
            baseline=baselines.get(finder.finder_id),
            live_rate=live_rates.get(finder.finder_id),
            now=now,
        )
        for finder in GENERATIVE_FINDERS
    ]
