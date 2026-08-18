"""Token-drift engine — the read-only half of the drift caretaker (#11441 salvage).

Pins a per-source-share + median-tokens-per-issue baseline over trailing ISO
weeks of :func:`token_report.build_token_report` rollups, then compares a
later trailing week against it using the same widened-limit control-band
arithmetic as the rest of the vitals fleet (ADR-0133): each baselined source
(plus the median-tokens chart) is one Shewhart individuals chart, and the
whole family's sigma multiplier ``L`` widens with the chart count so the
family's false-alarm rate stays bounded as sources are added — never a
hardcoded ``3.0``.

Pure engine, no filing, no caretaker wiring: :func:`check_drift` and
:func:`load_and_check_drift` return a :class:`DriftReport`; the only actuation
is display. ``src/token_drift.py`` is the frozen module contract the sibling
filing actuator (#11442) imports — do not rename or relocate the public names.

I/O is isolated to :class:`TokenBaselineLedger` (an
:class:`jsonl_ledger.AppendOnlyJsonlLedger` over
``<data_root>/calibration/token_baseline.jsonl``, mirroring
``finder_calibration.CalibrationLedger``) and :func:`load_and_check_drift`,
which is the fail-soft seam the diagnostics route calls: an unreadable or
corrupt ledger degrades to ``DriftStatus.NO_BASELINE``, never an exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finder_calibration import CALIBRATION_SUBDIR
from jsonl_ledger import AppendOnlyJsonlLedger
from prompt_telemetry import PromptTelemetry
from token_report import build_token_report
from vitals.control import sigma_hat
from vitals.models import VitalsThresholds
from vitals_methodology import widened_sigma_multiplier

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger(__name__)

#: The sentinel "source" name for the median-tokens-per-issue chart, carried
#: in the same flat ``DriftReport.sources`` list as the per-source entries.
MEDIAN_TOKENS_SOURCE = "median_tokens_per_issue"

#: A baseline needs at least this many pinned windows before its control
#: limits are trusted — the same priming floor the second-order vitals verdict
#: uses (src/vitals/models.py ``VitalsThresholds.min_baseline_windows``),
#: derived rather than re-hardcoded so the two floors cannot silently diverge.
MIN_BASELINE_WINDOWS = VitalsThresholds().min_baseline_windows

#: A baseline older than this is presumed to no longer reflect current
#: behaviour. 90 days (not the 30-day floor `finder_calibration` uses) because
#: a re-pin needs ``MIN_BASELINE_WINDOWS`` fresh weeks (56 days) of runway.
MAX_BASELINE_AGE = timedelta(days=90)

TOKEN_BASELINE_FILENAME = "token_baseline.jsonl"

#: Rows loaded per drift check — comfortably covers the single trailing
#: complete ISO week :func:`check_drift` examines, matching the existing
#: ``/token-report`` route's telemetry cap.
DRIFT_LOAD_LIMIT = 5000


class DriftStatus(StrEnum):
    """Top-level :class:`DriftReport` status."""

    OK = "ok"
    NO_BASELINE = "no_baseline"
    INSUFFICIENT_DATA = "insufficient_data"
    STALE = "stale"


class DriftVerdict(StrEnum):
    """Per-chart verdict within a :class:`DriftReport`."""

    OK = "ok"
    DRIFTING = "drifting"
    UNBASELINED = "unbaselined"


# --- models ------------------------------------------------------------------


@dataclass(frozen=True)
class TokenBaseline:
    """A pinned token baseline: per-window series for each chart.

    ``source_share_series`` and ``median_tokens_series`` carry ONE value per
    pinned window (oldest-first) rather than a pre-collapsed mean/sigma, so
    :func:`check_drift` can derive ``centre``/``σ̂`` via the same
    :func:`vitals.control.sigma_hat` estimator the rest of the vitals fleet
    uses — one home for that arithmetic.
    """

    pinned_at: datetime
    windows_counted: int
    source_share_series: dict[str, list[float]]
    median_tokens_series: list[float]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "pinned_at": self.pinned_at.isoformat(),
            "windows_counted": self.windows_counted,
            "source_share_series": self.source_share_series,
            "median_tokens_series": self.median_tokens_series,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> TokenBaseline:
        """Round-trip loader. Only ``pinned_at`` is required — a row missing
        any other (possibly newer) field defaults rather than raising, but a
        row that cannot even name when it was pinned is corrupt, not merely
        stale, and the caller must not silently treat it as valid. A
        timezone-naive ``pinned_at`` is likewise rejected here rather than
        left to blow up later as a ``TypeError`` when :func:`check_drift`
        subtracts it from an aware ``now``.
        """
        pinned_at = datetime.fromisoformat(str(raw["pinned_at"]))
        if pinned_at.tzinfo is None:
            raise ValueError(f"pinned_at must be timezone-aware, got {pinned_at!r}")
        return cls(
            pinned_at=pinned_at,
            windows_counted=int(raw.get("windows_counted", 0) or 0),
            source_share_series={
                str(source): [float(v) for v in series]
                for source, series in dict(raw.get("source_share_series") or {}).items()
            },
            median_tokens_series=[
                float(v) for v in (raw.get("median_tokens_series") or [])
            ],
        )


@dataclass(frozen=True)
class SourceDrift:
    """One chart's verdict: ``{source, before_share, after_share, sigma, verdict}``.

    ``before_share``/``after_share`` name the baseline-centre and current
    reading for whichever chart this is — a per-source token share, or (for
    :data:`MEDIAN_TOKENS_SOURCE`) the fleet's median tokens-per-issue. ``sigma``
    is ``(after - before) / σ̂``, ``None`` when the baseline had zero dispersion
    (a flat series breaches on any rise, but "how many sigma" is undefined).
    """

    source: str
    before_share: float | None
    after_share: float
    sigma: float | None
    verdict: DriftVerdict

    @property
    def is_drifting(self) -> bool:
        return self.verdict is DriftVerdict.DRIFTING

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "before_share": self.before_share,
            "after_share": self.after_share,
            "sigma": self.sigma,
            "verdict": self.verdict.value,
            "is_drifting": self.is_drifting,
        }


@dataclass(frozen=True)
class DriftReport:
    """The drift verdict for one trailing window against a pinned baseline."""

    status: DriftStatus
    reason: str
    sources: list[SourceDrift] = field(default_factory=list)
    window_key: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "window_key": self.window_key,
            "sources": [s.to_json_dict() for s in self.sources],
        }


# --- windowing -----------------------------------------------------------------


def _iso_week_key(dt: datetime) -> str:
    year, week, _weekday = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def iso_week_windows(
    rows: list[dict[str, Any]], *, now: datetime, windows: int
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Bucket *rows* into complete ISO-week windows, oldest-first.

    Rows in *now*'s own (still-open) week are dropped — a partial week is not
    a comparable window. Rows with a missing or unparseable ``timestamp`` are
    dropped silently; this is a pure rollup, not a validator. Returns at most
    the trailing *windows* complete weeks.
    """
    current_week = _iso_week_key(now)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ts = _parse_timestamp(row.get("timestamp"))
        if ts is None:
            continue
        week = _iso_week_key(ts)
        if week == current_week:
            continue
        buckets.setdefault(week, []).append(row)
    trailing_weeks = sorted(buckets)[-windows:] if windows > 0 else []
    return [(week, buckets[week]) for week in trailing_weeks]


# --- baseline pinning ------------------------------------------------------------


def pin_baseline(
    windows: list[tuple[str, list[dict[str, Any]]]], *, pinned_at: datetime
) -> TokenBaseline:
    """Pin a :class:`TokenBaseline` from pre-bucketed trailing windows.

    Each window is rolled up via :func:`token_report.build_token_report` with
    an explicit ``recent_issues`` sized to the window (the 25-issue default
    would silently truncate a busy week). A source missing from a given
    window's ``phase_share`` gets ``0.0`` for that window — the share is
    defined over the window's grand total, so "not present" IS a real zero,
    not a missing observation.
    """
    per_window_reports = [
        (week, build_token_report(rows, recent_issues=max(len(rows), 1)))
        for week, rows in windows
    ]
    all_sources = sorted(
        {
            entry["source"]
            for _, report in per_window_reports
            for entry in report["fleet"]["phase_share"]
        }
    )
    source_share_series: dict[str, list[float]] = {source: [] for source in all_sources}
    median_tokens_series: list[float] = []
    for _week, report in per_window_reports:
        shares = {e["source"]: e["share"] for e in report["fleet"]["phase_share"]}
        for source in all_sources:
            source_share_series[source].append(shares.get(source, 0.0))
        median_tokens_series.append(float(report["fleet"]["median_tokens_per_issue"]))
    return TokenBaseline(
        pinned_at=pinned_at,
        windows_counted=len(per_window_reports),
        source_share_series=source_share_series,
        median_tokens_series=median_tokens_series,
    )


# --- drift computation ------------------------------------------------------------


def _chart_drift(
    source: str,
    baseline_series: list[float],
    after: float,
    *,
    multiplier: float,
) -> SourceDrift:
    centre = sum(baseline_series) / len(baseline_series)
    spread = sigma_hat(baseline_series)
    limit = centre + multiplier * spread
    verdict = DriftVerdict.DRIFTING if after > limit else DriftVerdict.OK
    sigma = (after - centre) / spread if spread > 0 else None
    return SourceDrift(
        source=source,
        before_share=centre,
        after_share=after,
        sigma=sigma,
        verdict=verdict,
    )


def _build_source_drifts(
    baseline: TokenBaseline,
    current_shares: dict[str, float],
    median_tokens_per_issue: float,
    *,
    multiplier: float,
) -> list[SourceDrift]:
    """One :class:`SourceDrift` per baselined-or-current source, plus the
    median-tokens chart. A source with no baseline series is ``unbaselined``;
    everything else routes through :func:`_chart_drift`.
    """
    sources: list[SourceDrift] = []
    for source in sorted(set(baseline.source_share_series) | set(current_shares)):
        if source not in baseline.source_share_series:
            sources.append(
                SourceDrift(
                    source=source,
                    before_share=None,
                    after_share=current_shares.get(source, 0.0),
                    sigma=None,
                    verdict=DriftVerdict.UNBASELINED,
                )
            )
            continue
        sources.append(
            _chart_drift(
                source,
                baseline.source_share_series[source],
                current_shares.get(source, 0.0),
                multiplier=multiplier,
            )
        )
    sources.append(
        _chart_drift(
            MEDIAN_TOKENS_SOURCE,
            baseline.median_tokens_series,
            median_tokens_per_issue,
            multiplier=multiplier,
        )
    )
    return sources


def check_drift(
    baseline: TokenBaseline | None, rows: list[dict[str, Any]], *, now: datetime
) -> DriftReport:
    """Compare the latest trailing complete ISO week against *baseline*.

    Guardrails, evaluated in order, each degrading to a non-``ok`` status with
    a human-readable ``reason`` rather than raising or fabricating a verdict:
    no baseline; a baseline pinned from too few windows; a baseline old enough
    that "clean" no longer means what it meant; and an empty trailing window
    (nothing to compare).
    """
    if baseline is None:
        return DriftReport(
            status=DriftStatus.NO_BASELINE,
            reason="no baseline pinned; run scripts/pin_token_baseline.py --apply",
        )
    if baseline.windows_counted < MIN_BASELINE_WINDOWS:
        return DriftReport(
            status=DriftStatus.INSUFFICIENT_DATA,
            reason=(
                f"baseline pinned from only {baseline.windows_counted} window(s); "
                f"needs at least {MIN_BASELINE_WINDOWS}"
            ),
        )
    age = now - baseline.pinned_at
    if age > MAX_BASELINE_AGE:
        return DriftReport(
            status=DriftStatus.STALE,
            reason=(
                f"baseline pinned {age.days} day(s) ago; older than the "
                f"{MAX_BASELINE_AGE.days}-day limit — re-pin before trusting it"
            ),
        )
    trailing = iso_week_windows(rows, now=now, windows=1)
    if not trailing:
        return DriftReport(
            status=DriftStatus.INSUFFICIENT_DATA,
            reason="no issues in the trailing window",
        )
    window_key, window_rows = trailing[-1]
    report = build_token_report(window_rows, recent_issues=max(len(window_rows), 1))
    if report["fleet"]["issues_counted"] == 0:
        return DriftReport(
            status=DriftStatus.INSUFFICIENT_DATA,
            reason="no issues in the trailing window",
            window_key=window_key,
        )

    current_shares = {e["source"]: e["share"] for e in report["fleet"]["phase_share"]}
    charts = len(baseline.source_share_series) + 1  # +1 for the median chart
    multiplier = widened_sigma_multiplier(charts, two_sided=False)
    sources = _build_source_drifts(
        baseline,
        current_shares,
        float(report["fleet"]["median_tokens_per_issue"]),
        multiplier=multiplier,
    )
    drifting = sum(1 for s in sources if s.is_drifting)
    return DriftReport(
        status=DriftStatus.OK,
        reason=f"{len(sources)} chart(s) checked at L={multiplier:.2f}; {drifting} drifting",
        sources=sources,
        window_key=window_key,
    )


# --- ledger (append-only) -----------------------------------------------------------


def token_baseline_path(data_root: Path) -> Path:
    """Return ``<data_root>/calibration/token_baseline.jsonl``."""
    return data_root / CALIBRATION_SUBDIR / TOKEN_BASELINE_FILENAME


class TokenBaselineLedger:
    """Append-only ledger over one ``token_baseline.jsonl``; last row wins."""

    def __init__(self, path: Path) -> None:
        self._ledger: AppendOnlyJsonlLedger[TokenBaseline] = AppendOnlyJsonlLedger(
            path, TokenBaseline, logger=logger
        )

    @property
    def path(self) -> Path:
        return self._ledger.path

    def record(self, baseline: TokenBaseline) -> None:
        """Append one pinned baseline (creating the dir/file if needed)."""
        self._ledger.append(baseline)

    def latest(self) -> TokenBaseline | None:
        """The most recently pinned baseline, or ``None`` if never pinned."""
        rows = self._ledger.read_all()
        return rows[-1] if rows else None


def load_and_check_drift(
    config: HydraFlowConfig, *, now: datetime | None = None
) -> DriftReport:
    """Load the pinned baseline + recent telemetry and compute drift.

    The fail-soft seam the diagnostics route (and #11442) call: a ledger read
    failure — missing file, malformed JSON, or a row missing a required field
    (:meth:`TokenBaseline.from_json_dict` raises on those) — degrades to
    ``DriftStatus.NO_BASELINE`` rather than propagating, matching the rest of
    the diagnostics surface's never-500 contract.
    """
    now = now or datetime.now(UTC)
    try:
        baseline = TokenBaselineLedger(token_baseline_path(config.data_root)).latest()
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("token-drift: baseline ledger unreadable: %s", exc)
        return DriftReport(
            status=DriftStatus.NO_BASELINE,
            reason="baseline ledger unreadable; run scripts/pin_token_baseline.py --apply",
        )
    rows = PromptTelemetry(config).load_inferences(limit=DRIFT_LOAD_LIMIT)
    return check_drift(baseline, rows, now=now)
