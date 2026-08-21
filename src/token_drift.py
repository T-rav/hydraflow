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
``finder_calibration.CalibrationLedger``), :func:`load_window_rows` (the
telemetry reader — bounded by ISO week, never by row count, #11581) and
:func:`load_and_check_drift`, which is the fail-soft seam the diagnostics
route calls: an unreadable or corrupt ledger degrades to
``DriftStatus.NO_BASELINE``, a telemetry window the loader could not cover
completely degrades to ``DriftStatus.INSUFFICIENT_DATA`` — never an
exception, never a verdict on a partial window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
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
        subtracts it from an aware ``now`` — and a structurally corrupt field
        (a scalar where a series belongs, ``null`` inside a series) is
        converted to ``ValueError`` here for the same reason: ``ValueError``
        is the corrupt-row signal :func:`load_and_check_drift` catches, while
        a raw ``TypeError`` would escape it and 500 the diagnostics route.
        """
        pinned_at = datetime.fromisoformat(str(raw["pinned_at"]))
        if pinned_at.tzinfo is None:
            raise ValueError(f"pinned_at must be timezone-aware, got {pinned_at!r}")
        try:
            windows_counted = int(raw.get("windows_counted", 0) or 0)
            source_share_series = {
                str(source): [float(v) for v in series]
                for source, series in dict(raw.get("source_share_series") or {}).items()
            }
            median_tokens_series = [
                float(v) for v in (raw.get("median_tokens_series") or [])
            ]
        except TypeError as exc:
            raise ValueError(f"baseline row is structurally corrupt: {exc}") from exc
        return cls(
            pinned_at=pinned_at,
            windows_counted=windows_counted,
            source_share_series=source_share_series,
            median_tokens_series=median_tokens_series,
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
    """The drift verdict for one trailing window against a pinned baseline.

    :meth:`to_json_dict` also carries the window's Monday/Sunday dates
    (``window_start``/``window_end``) derived from ``window_key``, so a UI can
    render the comparison period without re-deriving ISO-week arithmetic.
    """

    status: DriftStatus
    reason: str
    sources: list[SourceDrift] = field(default_factory=list)
    window_key: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        start: date | None = None
        end: date | None = None
        if self.window_key:
            try:
                start, end = _iso_week_bounds(self.window_key)
            except ValueError:
                # to_json_dict is as fail-soft as the rest of the seam: an
                # unparseable window_key yields null dates, never an error.
                start, end = None, None
        return {
            "status": self.status.value,
            "reason": self.reason,
            "window_key": self.window_key,
            "window_start": start.isoformat() if start else None,
            "window_end": end.isoformat() if end else None,
            "sources": [s.to_json_dict() for s in self.sources],
        }


# --- windowing -----------------------------------------------------------------


def _iso_week_key(dt: date) -> str:
    year, week, _weekday = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _iso_week_bounds(week_key: str) -> tuple[date, date]:
    """The (Monday, Sunday) calendar dates of the ISO week *week_key* names."""
    year, week = week_key.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    return monday, monday + timedelta(days=6)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def trailing_complete_weeks(now: datetime, windows: int) -> tuple[str, ...]:
    """ISO-week keys of the *windows* complete weeks before *now*'s own
    (still-open) week, oldest-first; empty when *windows* is not positive.

    The one definition of "trailing complete week" shared by the loader
    (:func:`load_window_rows` keeps exactly these weeks) and the verdict
    (:func:`check_drift` demands the newest of them), so the two can never
    disagree about which calendar week is under comparison.
    """
    this_monday = now.date() - timedelta(days=now.weekday())
    return tuple(
        _iso_week_key(this_monday - timedelta(weeks=k)) for k in range(windows, 0, -1)
    )


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


def _baseline_guardrail(
    baseline: TokenBaseline, *, now: datetime
) -> DriftReport | None:
    """The guardrail that blocks checking *baseline*, or ``None`` to proceed.

    Evaluated in order — too few pinned windows; a structurally corrupt row; a
    stale pin — each degrading to a non-``ok`` status with a human-readable
    ``reason`` rather than raising or fabricating a verdict.
    """
    if baseline.windows_counted < MIN_BASELINE_WINDOWS:
        return DriftReport(
            status=DriftStatus.INSUFFICIENT_DATA,
            reason=(
                f"baseline pinned from only {baseline.windows_counted} window(s); "
                f"needs at least {MIN_BASELINE_WINDOWS}"
            ),
        )
    if len(baseline.median_tokens_series) != baseline.windows_counted or any(
        len(series) != baseline.windows_counted
        for series in baseline.source_share_series.values()
    ):
        # pin_baseline writes exactly one observation per window per chart, so
        # any disagreement means the row did not come from pin_baseline —
        # hand-edited, half-written, or foreign. Without this guard an empty
        # series would ZeroDivisionError inside _chart_drift, outside every
        # fail-soft net, and 500 the diagnostics route.
        return DriftReport(
            status=DriftStatus.NO_BASELINE,
            reason=(
                "baseline structurally corrupt (series lengths disagree with "
                "windows_counted); re-pin via scripts/pin_token_baseline.py --apply"
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
    return None


def check_drift(
    baseline: TokenBaseline | None,
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    truncation: str | None = None,
) -> DriftReport:
    """Compare the latest trailing complete ISO week against *baseline*.

    Guardrails, evaluated in order, each degrading to a non-``ok`` status with
    a human-readable ``reason`` rather than raising or fabricating a verdict:
    no baseline; a baseline pinned from too few windows; a structurally corrupt
    baseline (series that disagree with the row's ``windows_counted`` — the
    self-report is never trusted as a substitute for the actual series); a
    baseline old enough that "clean" no longer means what it meant; a
    *truncation* — the caller's statement that *rows* are known NOT to cover
    the trailing window completely (see :class:`TelemetryWindow`; a partial
    window is not a smaller window, it is no window, #11581); and an empty
    trailing window (nothing to compare). The trailing window is the
    calendar's latest complete week, not merely the newest week with data: a
    fleet idle last week gets ``insufficient_data``, never an ``ok`` verdict
    computed on older data as if the instrument were still watching.
    """
    if baseline is None:
        return DriftReport(
            status=DriftStatus.NO_BASELINE,
            reason="no baseline pinned; run scripts/pin_token_baseline.py --apply",
        )
    blocked = _baseline_guardrail(baseline, now=now)
    if blocked is not None:
        return blocked
    expected_week = trailing_complete_weeks(now, 1)[0]
    if truncation is not None:
        return DriftReport(
            status=DriftStatus.INSUFFICIENT_DATA,
            reason=f"trailing window {expected_week} is incomplete: {truncation}",
            window_key=expected_week,
        )
    trailing = iso_week_windows(rows, now=now, windows=1)
    if not trailing or trailing[-1][0] != expected_week:
        latest = trailing[-1][0] if trailing else "none"
        return DriftReport(
            status=DriftStatus.INSUFFICIENT_DATA,
            reason=(
                f"no issues in the trailing window ({expected_week}; "
                f"latest activity {latest})"
            ),
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
    # Only baselined (registered → actually sigma-tested) charts count toward
    # the family size: a current-week-only source is UNBASELINED and performs
    # no test, so it adds no false-alarm probability — counting it would
    # over-widen every real chart's limit. The baseline is the registration.
    charts = len(baseline.source_share_series) + 1  # +1 for the median chart
    multiplier = widened_sigma_multiplier(charts, two_sided=False)
    # One-sided L is floored at the classic 3.0 until the family is large —
    # it first lifts at 38 charts at the 5% monthly default — so at today's
    # source counts the limit IS centre + 3.0·σ̂; the widening is headroom
    # for family growth, not a wider band today.
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


# --- telemetry window loading ----------------------------------------------------


@dataclass(frozen=True)
class TelemetryWindow:
    """The telemetry rows of a span of trailing complete ISO weeks (#11581).

    ``weeks`` names the span (oldest-first), ``rows`` carries every row whose
    ``timestamp`` falls in it — bounded by the window, never by a row count —
    and ``truncation`` is the loader's honest statement of why the span is
    known to be incomplete (``None`` when its coverage can be trusted). A
    consumer must treat a truncated span as NO window: the rows that are
    present would roll up into confident, wrong shares.
    """

    weeks: tuple[str, ...]
    rows: list[dict[str, Any]]
    truncation: str | None = None

    @property
    def truncated(self) -> bool:
        return self.truncation is not None


def _retention_truncation(
    config: HydraFlowConfig, weeks: tuple[str, ...], *, now: datetime
) -> str | None:
    """Why *weeks* may already have lost rows to the telemetry retention floor.

    ``RunsGCLoop`` prunes ``inferences.jsonl`` records strictly older than
    ``now - audit_retention_days_inference_telemetry`` (``None`` = keep
    forever). A floor that falls after the oldest week's Monday 00:00 UTC
    may have taken that week's head; whether the prune has actually run is
    unknowable here, so the span is reported truncated either way.
    """
    days = config.audit_retention_days_inference_telemetry
    if not weeks or not isinstance(days, int):
        return None
    cutoff = now - timedelta(days=days)
    oldest_monday = datetime.combine(
        _iso_week_bounds(weeks[0])[0], time.min, tzinfo=UTC
    )
    if oldest_monday >= cutoff:
        return None
    return (
        f"window {weeks[0]} starts before the {days}-day telemetry retention "
        f"floor ({cutoff.date().isoformat()}); its rows may already be pruned"
    )


def load_window_rows(
    config: HydraFlowConfig, *, now: datetime, windows: int
) -> TelemetryWindow:
    """Stream ``inferences.jsonl`` and keep the rows of the *windows* trailing
    complete ISO weeks before *now* — bounded by WINDOW, never by row count.

    A fixed row cap is a blind instrument that reports confidently: live
    telemetry carried 24,434 rows in one ISO week (2026-W25), so a 5,000-row
    tail either lost the trailing week entirely (``insufficient_data`` in
    exactly the high-burn weeks the sensor exists for) or kept a mid-week
    slice and mis-sampled the shares (#11581). Rows outside the span — older
    weeks, the still-open week — and rows with no parseable ``timestamp`` are
    skipped as they stream, so memory holds the span, not the file.

    The span's coverage is reported honestly via ``truncation``: a read that
    died mid-stream (rows already kept cannot be un-kept) or a retention floor
    inside the oldest week (:func:`_retention_truncation`). A missing file is
    an empty, complete span — nothing was cut from it.
    """
    weeks = trailing_complete_weeks(now, windows)
    wanted = frozenset(weeks)
    rows: list[dict[str, Any]] = []
    try:
        for row in PromptTelemetry(config).iter_inferences():
            ts = _parse_timestamp(row.get("timestamp"))
            if ts is not None and _iso_week_key(ts) in wanted:
                rows.append(row)
    except OSError as exc:
        logger.warning("token-drift: telemetry unreadable: %s", exc)
        return TelemetryWindow(
            weeks=weeks,
            rows=rows,
            truncation=f"telemetry unreadable ({exc.strerror or exc})",
        )
    return TelemetryWindow(
        weeks=weeks, rows=rows, truncation=_retention_truncation(config, weeks, now=now)
    )


def load_and_check_drift(
    config: HydraFlowConfig, *, now: datetime | None = None
) -> DriftReport:
    """Load the pinned baseline + the trailing week's telemetry and compute drift.

    The fail-soft seam the diagnostics route (and #11442) call: a ledger read
    failure — missing file, malformed JSON, or a row missing a required field
    (:meth:`TokenBaseline.from_json_dict` raises on those) — degrades to
    ``DriftStatus.NO_BASELINE`` rather than propagating, and a telemetry
    window the loader could not cover completely (:class:`TelemetryWindow`)
    degrades to ``DriftStatus.INSUFFICIENT_DATA`` rather than a verdict,
    matching the rest of the diagnostics surface's never-500 contract.
    Nothing pinned short-circuits before the telemetry is streamed — the
    answer is ``no_baseline`` regardless of what the file holds.
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
    if baseline is None:
        return check_drift(None, [], now=now)
    window = load_window_rows(config, now=now, windows=1)
    return check_drift(baseline, window.rows, now=now, truncation=window.truncation)
