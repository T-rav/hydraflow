"""Golden-baseline finder calibration — noise-floor engine (pure core). #10821.

A *generative* finder has no natural zero. An LLM asked to "find erosion" or
"propose edges" against a repository will always find *something* — so its
output against a **known-clean baseline** (a hand-vetted sha where the answer
for a given signal class is "nothing to find") is not a real signal: it is that
finder's **false-positive floor**, its sensor noise. This module measures that
floor, sets an actuation threshold *above* it, and flags when a finder's live
output is statistically indistinguishable from its own noise.

This is the **Kalman R for LLM finders**: R is the measurement-noise covariance
a filter must know before it can trust a sensor. Here the noise floor's
``(mean, sigma)`` over repeated runs against the clean baseline *is* R. You do
not assume it (a Poisson prior would under-state it — LLM-finder noise is
over-dispersed, mostly-zero with a heavy tail); you **measure** it.

Design constraints honoured by this slice:

* **Pure core, no I/O on the hot path** — the math (``measure_floor``,
  ``threshold_above_floor``, ``indistinguishable_from_floor``, ``propose_gain``)
  is subprocess-free and fully unit-testable, mirroring ``mutation_gauntlet``.
* **Read-only / propose-only** — the engine's only actuation output is a
  :class:`GainProposal`. It NEVER edits a finder, mutates config, or actions a
  finding. A proposal is a recommendation for a human/loop to apply later.
* **Injected measurement seam** — real finders are expensive and
  non-deterministic, so this slice does NOT run them. It defines the
  :class:`FinderRunner` protocol; the ledger + core consume counts a runner
  produces. Wiring a real finder-loop invocation against a checked-out sha is
  the documented Phase-2 seam.

Shewhart reuse (see ADR-0126): the confident-path UCL is a fresh individuals
chart (``mean + k·sigma`` over the *measured* empirical sigma) because neither
existing helper computes it — ``audit.governance.upper_control_limit`` is a
p-chart anchored to a fixed target proportion, and
``judge_independence.shewhart_c_chart_ucl`` assumes Poisson dispersion. That
c-chart helper *is* reused, honestly, for the low-confidence (<2 sample)
fallback where an empirical sigma cannot be measured and the Poisson prior is
the only principled choice. Consolidating both into a shared ``shewhart`` module
is a documented follow-up.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from jsonl_ledger import AppendOnlyJsonlLedger
from judge_independence import shewhart_c_chart_ucl

logger = logging.getLogger(__name__)

# --- calibration constants (planning-picked v1) --------------------------------

#: Shewhart control constant. 3-sigma is the classic Shewhart convention: an
#: in-control process exceeds mean + 3-sigma only ~0.13% of the time, so a live
#: count above it is special-cause, not noise.
DEFAULT_SIGMA_K = 3.0

#: Below this sample count an empirical sigma cannot be measured; the floor is
#: marked low-confidence and ``propose_gain`` will not act on it.
MIN_CONFIDENT_SAMPLES = 2

#: A golden baseline older than this is presumed stale — the tree it vetted has
#: moved on, so "clean" no longer means what it meant. A stale baseline silently
#: miscalibrates every finder measured against it, so this is a hard guardrail.
DEFAULT_MAX_BASELINE_AGE = timedelta(days=30)

#: Ledger location under the data root: ``<data_root>/calibration/<file>``.
CALIBRATION_SUBDIR = "calibration"
FLOORS_FILENAME = "finder_floors.jsonl"


# --- generative-finder catalog -------------------------------------------------


@dataclass(frozen=True)
class GenerativeFinder:
    """One generative finder in scope for noise-floor calibration.

    ``finder_id`` is the stable key the ledger + runner seam use; ``signal_class``
    is the family of thing the finder generates (what "clean" means is defined
    per class — a baseline vetted clean *for erosion* need not be clean for
    *wiki-rot*).
    """

    finder_id: str
    signal_class: str
    description: str


#: Curated catalog of the clear generative finders (the ones an LLM drives to
#: *find/propose*, which therefore have a false-positive floor rather than a
#: natural zero). Deliberately small — the point is the shape, not exhaustive
#: coverage; broadening the catalog is Phase-2 work.
GENERATIVE_FINDERS: tuple[GenerativeFinder, ...] = (
    GenerativeFinder(
        "erosion_metrics",
        "erosion",
        "ErosionMetricsLoop — LLM-scored concept-scatter / erosion findings.",
    ),
    GenerativeFinder(
        "edge_proposer",
        "edges",
        "EdgeProposerLoop — proposes depends_on / implements term-map edges.",
    ),
    GenerativeFinder(
        "entry_evidence",
        "wiki-evidence",
        "EntryEvidenceLoop — proposes wiki-entry matches as Term.evidence.",
    ),
    GenerativeFinder(
        "term_proposer",
        "glossary-terms",
        "TermProposerLoop — proposes new ubiquitous-language glossary terms.",
    ),
    GenerativeFinder(
        "wiki_rot",
        "wiki-rot",
        "WikiRotDetectorLoop — flags stale wiki citations as rot findings.",
    ),
)

#: ``finder_id`` -> :class:`GenerativeFinder` for O(1) lookup.
FINDERS_BY_ID: dict[str, GenerativeFinder] = {
    f.finder_id: f for f in GENERATIVE_FINDERS
}


# --- models --------------------------------------------------------------------


@dataclass(frozen=True)
class GoldenBaseline:
    """A hand-vetted sha where a given ``signal_class`` has *nothing to find*.

    Running a finder here should ideally flag zero; whatever it *does* flag is
    that finder's noise. ``vetted_at`` / ``vetted_by`` anchor the staleness
    guardrail and the audit trail for why this tree was trusted as clean.
    """

    sha: str
    vetted_at: datetime
    vetted_by: str
    signal_class: str
    note: str = ""


@dataclass(frozen=True)
class NoiseSample:
    """One measurement: how many things ``finder_id`` flagged on the clean
    baseline in a single run. The raw datum the noise floor is built from.
    """

    finder_id: str
    baseline_sha: str
    flagged_count: int
    ran_at: datetime


@dataclass(frozen=True)
class FinderFloor:
    """A finder's measured noise floor + the actuation threshold set above it.

    ``floor_mean`` / ``floor_sigma`` are the measured noise covariance (the
    "Kalman R"). ``threshold`` is the Shewhart UCL: live output at or below it is
    indistinguishable from noise. ``mean_drift`` records how far ``floor_mean``
    moved from the *previous* calibration (value drift — a finder whose floor
    keeps moving is unstable); ``last_calibrated`` anchors the *temporal* drift
    clock (see :func:`drift_since`).
    """

    finder_id: str
    floor_mean: float
    floor_sigma: float
    sample_count: int
    threshold: int
    last_calibrated: datetime
    mean_drift: float = 0.0

    @property
    def low_confidence(self) -> bool:
        """True when too few samples backed the sigma to trust the floor."""
        return self.sample_count < MIN_CONFIDENT_SAMPLES

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "finder_id": self.finder_id,
            "floor_mean": self.floor_mean,
            "floor_sigma": self.floor_sigma,
            "sample_count": self.sample_count,
            "threshold": self.threshold,
            "last_calibrated": self.last_calibrated.isoformat(),
            "mean_drift": self.mean_drift,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> FinderFloor:
        return cls(
            finder_id=str(raw["finder_id"]),
            floor_mean=float(raw.get("floor_mean", 0.0) or 0.0),
            floor_sigma=float(raw.get("floor_sigma", 0.0) or 0.0),
            sample_count=int(raw.get("sample_count", 0) or 0),
            threshold=int(raw.get("threshold", 0) or 0),
            last_calibrated=datetime.fromisoformat(str(raw["last_calibrated"])),
            mean_drift=float(raw.get("mean_drift", 0.0) or 0.0),
        )


@dataclass(frozen=True)
class GainProposal:
    """A *recommendation* to change a finder's gain (its actuation threshold).

    This is the engine's ONLY actuation output and it is inert: it names the
    finder, the current and proposed threshold, and why. Applying it is a
    separate, human/loop-gated step. The engine never mutates a finder itself.
    """

    finder_id: str
    current_threshold: int
    proposed_threshold: int
    reason: str


# --- measurement seam (injected; NOT run live in this slice) -------------------


class FinderRunner(Protocol):
    """The injected seam that produces a flagged-count for a finder on a baseline.

    A real implementation would check out ``baseline.sha`` and invoke the finder
    loop against it — expensive and non-deterministic, hence deferred to Phase 2.
    The pure core + ledger only ever consume the returned count, so tests inject
    a fake runner returning known counts.
    """

    def run_against_baseline(self, finder_id: str, baseline: GoldenBaseline) -> int:
        """Return how many items *finder_id* flags on *baseline* in one run."""
        ...


def collect_samples(
    runner: FinderRunner,
    finder_id: str,
    baseline: GoldenBaseline,
    *,
    runs: int,
    ran_at: datetime,
) -> list[NoiseSample]:
    """Drive *runner* ``runs`` times over the clean baseline, one sample each.

    Pure with respect to *runner*: it only calls the injected seam and packages
    counts into :class:`NoiseSample` rows. Does no git checkout and no finder
    invocation of its own.
    """
    return [
        NoiseSample(
            finder_id=finder_id,
            baseline_sha=baseline.sha,
            flagged_count=runner.run_against_baseline(finder_id, baseline),
            ran_at=ran_at,
        )
        for _ in range(max(0, runs))
    ]


# --- the noise-floor math (pure) ----------------------------------------------


def measure_floor(samples: Sequence[NoiseSample]) -> tuple[float, float]:
    """Measure a finder's noise floor ``(mean, sigma)`` from clean-baseline samples.

    The mean flagged-count is the floor's centre; the sample standard deviation
    (``ddof=1`` — we estimate the population sigma from a sample) is its spread,
    the measured sensor-noise covariance.

    Degenerate cases are handled honestly, never by crashing:

    * **0 samples** → ``(0.0, 0.0)``; there is no floor yet. The caller marks the
      resulting floor low-confidence via ``sample_count``.
    * **1 sample** → an empirical sigma is *undefined* from one point. Fall back
      to the Poisson (Shewhart c-chart) dispersion assumption ``variance == mean``
      i.e. ``sigma == sqrt(mean)`` — a deliberately *wider* prior than "zero
      spread". This reuses :func:`judge_independence.shewhart_c_chart_ucl` as the
      single source of that assumption: with ``sigma = sqrt(mean)`` and ``k = 3``,
      ``mean + k·sigma == cbar + 3·sqrt(cbar) == shewhart_c_chart_ucl``.
    """
    counts = [float(s.flagged_count) for s in samples]
    n = len(counts)
    if n == 0:
        return (0.0, 0.0)
    mean = sum(counts) / n
    if n < MIN_CONFIDENT_SAMPLES:
        # sigma undefined from a single point → widen with the Poisson prior,
        # sourced from the existing c-chart UCL helper so there is one home for
        # that assumption. shewhart_c_chart_ucl([m]) == m + 3*sqrt(m); recover
        # sigma = (ucl - mean) / 3 == sqrt(mean) (0 when mean is 0).
        poisson_ucl = shewhart_c_chart_ucl(counts)
        sigma = (poisson_ucl - mean) / 3.0 if mean > 0 else 0.0
        return (mean, sigma)
    variance = sum((c - mean) ** 2 for c in counts) / (n - 1)
    return (mean, math.sqrt(variance))


def threshold_above_floor(
    mean: float, sigma: float, *, k: float = DEFAULT_SIGMA_K
) -> int:
    """Actuation threshold = the Shewhart UCL ``mean + k·sigma``, sanely floored.

    Rounded UP (``ceil``) to a whole count — the threshold is compared against
    integer flagged-counts, and rounding down would let a count exactly on the
    limit read as signal. Floored at 0 so a clean, low-variance floor never
    yields a negative threshold. Live output must exceed this to be actionable.
    """
    ucl = mean + k * sigma
    return max(0, math.ceil(ucl))


def indistinguishable_from_floor(
    live_count: int, mean: float, sigma: float, *, k: float = DEFAULT_SIGMA_K
) -> bool:
    """True when *live_count* sits inside the floor's control limits.

    Inside the limits ⇒ the finder's live output is statistically the same as
    what it produces against a known-clean baseline ⇒ it is finding **noise**,
    which is the trigger for a review/gain-down. Only a count strictly above the
    UCL is distinguishable signal.
    """
    return live_count <= threshold_above_floor(mean, sigma, k=k)


def calibrate_finder(
    finder_id: str,
    samples: Sequence[NoiseSample],
    now: datetime,
    *,
    prior: FinderFloor | None = None,
    k: float = DEFAULT_SIGMA_K,
) -> FinderFloor:
    """Build a :class:`FinderFloor` from clean-baseline samples. Pure.

    ``mean_drift`` is the absolute shift in floor mean from *prior* (0.0 on a
    first calibration) — the value-drift signal the ledger persists per finder.
    """
    mean, sigma = measure_floor(samples)
    threshold = threshold_above_floor(mean, sigma, k=k)
    mean_drift = abs(mean - prior.floor_mean) if prior is not None else 0.0
    return FinderFloor(
        finder_id=finder_id,
        floor_mean=mean,
        floor_sigma=sigma,
        sample_count=len(samples),
        threshold=threshold,
        last_calibrated=now,
        mean_drift=mean_drift,
    )


def propose_gain(floor: FinderFloor, current_threshold: int) -> GainProposal | None:
    """Propose turning a finder's gain DOWN when its threshold is below the floor.

    A finder whose actuation threshold sits at or below the measured noise-floor
    UCL will fire on output indistinguishable from its own noise. The remedy is
    to raise the threshold (turn gain down) to the measured floor. This function
    is strictly **read-only**: it returns a :class:`GainProposal` (or ``None``)
    and mutates nothing — not *floor*, not any finder, not any finding.

    Returns ``None`` when there is nothing to propose:

    * the floor is low-confidence (too few samples to justify a change), or
    * the current threshold already sits above the measured floor.
    """
    if floor.low_confidence:
        return None
    if current_threshold >= floor.threshold:
        return None
    reason = (
        f"current threshold {current_threshold} is at/below the measured noise "
        f"floor UCL {floor.threshold} (mean={floor.floor_mean:.2f}, "
        f"sigma={floor.floor_sigma:.2f}, n={floor.sample_count}); the finder "
        f"would actuate on output indistinguishable from its own noise. Propose "
        f"raising the threshold (turn gain DOWN) to {floor.threshold}."
    )
    return GainProposal(
        finder_id=floor.finder_id,
        current_threshold=current_threshold,
        proposed_threshold=floor.threshold,
        reason=reason,
    )


# --- staleness / drift guardrails ---------------------------------------------


def is_baseline_stale(
    baseline: GoldenBaseline,
    now: datetime,
    max_age: timedelta = DEFAULT_MAX_BASELINE_AGE,
) -> bool:
    """True when *baseline* is older than *max_age* — its "clean" is untrustworthy.

    A stale baseline silently miscalibrates every finder measured against it, so
    callers must refuse to calibrate from one (or flag the resulting floors).
    """
    return (now - baseline.vetted_at) > max_age


def drift_since(floor: FinderFloor, now: datetime) -> timedelta:
    """Temporal drift: how long since *floor* was last calibrated.

    The recalibration clock. Distinct from :attr:`FinderFloor.mean_drift`, which
    measures *value* drift (how far the floor mean moved between calibrations);
    this measures *time* drift. A large value means the floor may no longer
    reflect the finder's current behaviour and should be re-measured.
    """
    return now - floor.last_calibrated


# --- ledger (append-only, per-finder) -----------------------------------------


def calibration_ledger_path(data_root: Path) -> Path:
    """Return ``<data_root>/calibration/finder_floors.jsonl``."""
    return data_root / CALIBRATION_SUBDIR / FLOORS_FILENAME


class CalibrationLedger:
    """Append-only per-finder floor ledger over one ``finder_floors.jsonl``.

    Each :func:`calibrate_finder` result is appended as a row; the latest row per
    ``finder_id`` wins (:meth:`latest_by_finder`). Reuses the shared
    :class:`jsonl_ledger.AppendOnlyJsonlLedger` I/O and tolerates a missing file
    (reads as empty).
    """

    def __init__(self, path: Path) -> None:
        self._ledger: AppendOnlyJsonlLedger[FinderFloor] = AppendOnlyJsonlLedger(
            path, FinderFloor, logger=logger
        )

    @property
    def path(self) -> Path:
        return self._ledger.path

    def record(self, floor: FinderFloor) -> None:
        """Append one floor snapshot (creating the dir/file if needed)."""
        self._ledger.append(floor)

    def read_all(self) -> list[FinderFloor]:
        """Every recorded floor row, oldest first; ``[]`` when absent."""
        return self._ledger.read_all()

    def latest_by_finder(self) -> dict[str, FinderFloor]:
        """Map ``finder_id`` -> its most recently recorded floor.

        Append-only, so a later row supersedes an earlier one for the same
        finder (last write wins).
        """
        index: dict[str, FinderFloor] = {}
        for floor in self._ledger.read_all():
            index[floor.finder_id] = floor
        return index
