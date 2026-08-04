"""Judge calibration — proper-scoring instrument (pure core). #10836.

Third instrument in the "measure the factory's own quality machinery" trilogy.
The mutation gauntlet (``src/mutation_gauntlet.py``, #10835) measures **gate
sensitivity** — does a gate go red for a fault it owns? The finder calibration
(``src/finder_calibration.py``, #10821) measures **finder noise** — what does a
generative finder flag against a known-clean baseline? This module measures the
third quantity: **judge quality** — when a judge (a reviewer, an advisor) passes
or vetoes a change with a stated confidence, is that confidence *earned*?

A verdict with a probability attached is a **forecast**, and forecasts are
scored with **proper scoring rules** that reward honesty (a forecaster minimizes
its expected score only by reporting its true belief). This module scores each
judge's verdicts against their eventual outcomes with the two canonical rules —
the **Brier score** (mean squared error of the probability) and the **log score**
(the negative log-likelihood / cross-entropy) — and decomposes the result into
the two axes the #10836 issue insists are separate:

* **Calibration** — does 80% confidence actually mean 80% correct? Measured by
  the reliability curve (:func:`calibration_curve`) and its scalar summary, the
  expected calibration error (:func:`calibration_error`). A judge can be
  perfectly calibrated and still *useless* (always says 50% and is right half
  the time).
* **Discrimination** — does the judge separate good changes from bad *at all*?
  Measured by the AUC (:func:`discrimination`): the probability it assigns a
  higher P(good) to a randomly chosen good change than to a randomly chosen bad
  one. 0.5 is a coin flip; a judge can be sharply discriminating and badly
  miscalibrated (right *ordering*, wrong *numbers*).

The two are orthogonal, so this instrument reports **both** — a judge is only
trustworthy when it is calibrated *and* discriminating.

Design constraints (mirroring the two shipped siblings):

* **Pure core, no I/O on the hot path** — every scoring function
  (:func:`to_forecast`, :func:`resolve`, :func:`brier_score`, :func:`log_score`,
  :func:`calibration_curve`, :func:`calibration_error`, :func:`discrimination`,
  :func:`score_judge`, :func:`score_all`) is subprocess-free, LLM-free, and
  fully unit-testable on known distributions with hand-computed expectations.
* **Append-only ledger** — verdicts persist one-per-line to
  ``<data_root>/calibration/judge_verdicts.jsonl`` via the shared
  :class:`jsonl_ledger.AppendOnlyJsonlLedger`, exactly like the finder floors.
* **Injected outcome seam** — the ground truth ("was the change actually good?")
  is resolved from the *escape ledger* (#10367) through the injected
  :class:`OutcomeResolver` protocol. The pure engine consumes :class:`Outcome`
  rows; :class:`EscapeLedgerOutcomeResolver` is a thin, data-in adapter (it holds
  escape *records*, not the ledger file), so the endpoint owns the I/O and tests
  inject synthetic escapes.
* **Honest degeneracy** — nothing crashes on thin or lopsided data. Zero
  resolved forecasts → every metric ``None`` and ``low_confidence`` set, never a
  divide-by-zero. All-good-or-all-bad outcomes → discrimination is *undefined*
  (``None``), flagged rather than faked as 0.5.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from jsonl_ledger import AppendOnlyJsonlLedger

logger = logging.getLogger(__name__)

# --- calibration constants (planning-picked v1) --------------------------------

#: Number of equal-width bins the reliability curve partitions ``[0, 1]`` into.
#: Ten is the reliability-diagram convention (deciles of predicted probability).
DEFAULT_CALIBRATION_BINS = 10

#: Below this many *resolved* forecasts a judge's scores are statistically thin —
#: a single flip swings the Brier meaningfully — so the score is marked
#: low-confidence. Not a crash guard (the math is defined for n>=1); a caveat
#: flag the panel renders so a 3-sample "perfect" judge is not read as proven.
MIN_CONFIDENT_RESOLVED = 10

#: Log score clips predicted probabilities into ``[eps, 1-eps]`` so a confident,
#: wrong forecast (p==0 for a good outcome) yields a large-but-finite penalty
#: instead of ``+inf``. 1e-15 is small enough not to distort ordinary scores.
LOG_SCORE_EPS = 1e-15

#: How long after a verdict a subject must stay escape-free before it is scored
#: as *good*. Escapes surface with a lag (a revert lands in hours, a filed bug
#: can take days), so calling a fresh merge "good" the instant it lands would
#: over-credit every judge that just passed it. Seven days clears the bulk of
#: the escape-detection distribution while still resolving verdicts within a
#: week. An attributed escape marks *bad* immediately (no wait); only the
#: *good* verdict waits out the window. Tunable as escape time-to-detection data
#: accumulates.
DEFAULT_GRACE_WINDOW = timedelta(days=7)

#: Ledger location under the data root: ``<data_root>/calibration/<file>`` —
#: shares the ``calibration`` subdir with the finder floors (#10821).
CALIBRATION_SUBDIR = "calibration"
VERDICTS_FILENAME = "judge_verdicts.jsonl"


class Verdict(StrEnum):
    """A judge's binary call on a change — the direction of its forecast.

    ``PASS`` means "this change is good, merge it"; ``FAIL`` means "this change
    is bad, block it". :func:`to_forecast` maps the ``(verdict, confidence)``
    pair to a single predicted probability that the change is good.
    """

    PASS = "pass"
    FAIL = "fail"


# --- subject keying ------------------------------------------------------------


def subject_for_pr(pr_number: int) -> str:
    """Canonical subject id for a pull request — the escape-join key.

    The escape ledger attributes an escape to its ``originating_pr``, so verdicts
    keyed by PR number join cleanly to escapes. Format: ``"pr:<n>"``.
    """
    return f"pr:{pr_number}"


def subject_for_issue(issue_number: int) -> str:
    """Fallback subject id when no PR number is known — ``"issue:<n>"``.

    Escapes are keyed by PR, so issue-keyed verdicts will not resolve against the
    escape ledger; they are recorded honestly and simply report as unresolved
    until a PR-keyed verdict for the same change lands.
    """
    return f"issue:{issue_number}"


# --- models --------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeVerdictRecord:
    """One judge's verdict on one subject, with its stated confidence.

    The append-only ledger row. ``confidence`` is the judge's probability that
    its *own verdict* is correct (0.0-1.0), NOT directly P(good) — the direction
    is carried by ``verdict`` and combined by :func:`to_forecast`. ``subject_id``
    is the escape-join key (see :func:`subject_for_pr`).
    """

    judge_id: str
    judge_family: str
    subject_id: str
    verdict: Verdict
    confidence: float
    recorded_at: datetime

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "judge_id": self.judge_id,
            "judge_family": self.judge_family,
            "subject_id": self.subject_id,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> JudgeVerdictRecord:
        return cls(
            judge_id=str(raw["judge_id"]),
            judge_family=str(raw.get("judge_family", "")),
            subject_id=str(raw["subject_id"]),
            verdict=Verdict(str(raw["verdict"])),
            confidence=float(raw.get("confidence", 0.0) or 0.0),
            recorded_at=datetime.fromisoformat(str(raw["recorded_at"])),
        )


@dataclass(frozen=True)
class Outcome:
    """The resolved ground truth for one subject: ``good`` iff no escape.

    A subject with an escape attributed to it is ``good=False`` (whatever judge
    passed it was wrong); a subject that stayed escape-free past the grace window
    is ``good=True``. Subjects still inside the grace window are *unresolved* and
    never become an ``Outcome`` — the resolver simply omits them.
    """

    subject_id: str
    good: bool


@dataclass(frozen=True)
class ResolvedForecast:
    """A judge verdict joined to its outcome — the atom scoring consumes.

    ``predicted_good`` is the forecast probability the change is good (from
    :func:`to_forecast`); ``actual_good`` is the ground truth. A proper scoring
    rule compares these two.
    """

    judge_id: str
    judge_family: str
    subject_id: str
    predicted_good: float
    actual_good: bool


@dataclass(frozen=True)
class CalibrationBin:
    """One point on a judge's reliability curve.

    Within this decile of predicted probability, ``mean_confidence`` is the
    average forecast and ``empirical_rate`` is the fraction that were actually
    good. A perfectly calibrated judge has ``mean_confidence == empirical_rate``
    in every bin (points sit on the diagonal). ``n`` is the bin population.
    """

    bin_index: int
    mean_confidence: float
    empirical_rate: float
    n: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "bin_index": self.bin_index,
            "mean_confidence": self.mean_confidence,
            "empirical_rate": self.empirical_rate,
            "n": self.n,
        }


@dataclass(frozen=True)
class JudgeScore:
    """One judge's proper-scoring report — calibration AND discrimination.

    ``brier`` / ``log_score`` are the overall proper scores (lower is better).
    ``calibration_error`` (expected calibration error) + ``calibration_bins``
    are the *calibration* axis; ``discrimination`` (AUC) is the *separability*
    axis — a judge is only trustworthy when both are good. Every scalar is
    ``None`` under the degenerate condition that makes it undefined (no resolved
    forecasts → all ``None``; all-good or all-bad outcomes → ``discrimination``
    undefined, ``discrimination_undefined`` set). ``low_confidence`` flags a
    thin sample (see :data:`MIN_CONFIDENT_RESOLVED`).
    """

    judge_id: str
    judge_family: str
    n_resolved: int
    brier: float | None
    log_score: float | None
    calibration_error: float | None
    calibration_bins: tuple[CalibrationBin, ...]
    discrimination: float | None
    low_confidence: bool
    discrimination_undefined: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "judge_id": self.judge_id,
            "judge_family": self.judge_family,
            "n_resolved": self.n_resolved,
            "brier": self.brier,
            "log_score": self.log_score,
            "calibration_error": self.calibration_error,
            "calibration_bins": [b.to_json_dict() for b in self.calibration_bins],
            "discrimination": self.discrimination,
            "low_confidence": self.low_confidence,
            "discrimination_undefined": self.discrimination_undefined,
        }


# --- forecast mapping + join (pure) -------------------------------------------


def to_forecast(verdict: Verdict, confidence: float) -> float:
    """Map a ``(verdict, confidence)`` pair to a predicted probability of *good*.

    A judge states confidence in its *own verdict*; the forecast is the implied
    P(good):

    * ``PASS`` @ 0.9 → the judge is 90% sure the change is good → ``0.9``.
    * ``FAIL`` @ 0.9 → the judge is 90% sure the change is bad → ``0.1`` good.

    Confidence is clamped to ``[0, 1]`` so a malformed record can never produce a
    forecast outside the unit interval (which would break the proper scores).
    """
    clamped = min(max(confidence, 0.0), 1.0)
    return clamped if verdict is Verdict.PASS else 1.0 - clamped


def resolve(
    verdicts: Sequence[JudgeVerdictRecord], outcomes: Sequence[Outcome]
) -> list[ResolvedForecast]:
    """Join verdicts to outcomes by ``subject_id``; drop the unresolved.

    A verdict whose subject has no outcome yet (still inside the grace window, or
    never merged) is honestly dropped rather than guessed — the resolved count is
    reported so a small denominator is visible. Order follows *verdicts*.
    """
    outcome_by_subject = {o.subject_id: o for o in outcomes}
    resolved: list[ResolvedForecast] = []
    for v in verdicts:
        outcome = outcome_by_subject.get(v.subject_id)
        if outcome is None:
            continue
        resolved.append(
            ResolvedForecast(
                judge_id=v.judge_id,
                judge_family=v.judge_family,
                subject_id=v.subject_id,
                predicted_good=to_forecast(v.verdict, v.confidence),
                actual_good=outcome.good,
            )
        )
    return resolved


# --- proper scoring rules (pure) ----------------------------------------------


def brier_score(forecasts: Sequence[ResolvedForecast]) -> float | None:
    """Mean squared error of the forecast — the Brier score (lower is better).

    ``mean((p - y)^2)`` with ``y in {0, 1}``. Ranges ``[0, 1]``: 0 is perfect,
    0.25 is the always-0.5 baseline, 1 is confidently-always-wrong. ``None`` for
    an empty set (no evidence, not "0.0").
    """
    if not forecasts:
        return None
    total = sum(
        (f.predicted_good - (1.0 if f.actual_good else 0.0)) ** 2 for f in forecasts
    )
    return total / len(forecasts)


def log_score(forecasts: Sequence[ResolvedForecast]) -> float | None:
    """Mean negative log-likelihood — the log score / cross-entropy (lower better).

    ``mean(-(y·ln p + (1-y)·ln(1-p)))``. Punishes confident wrongness far harder
    than the Brier does. ``p`` is clipped into ``[eps, 1-eps]`` (see
    :data:`LOG_SCORE_EPS`) so a p==0 forecast for a good outcome yields a large
    finite penalty, never ``+inf``. ``None`` for an empty set.
    """
    if not forecasts:
        return None
    total = 0.0
    for f in forecasts:
        p = min(max(f.predicted_good, LOG_SCORE_EPS), 1.0 - LOG_SCORE_EPS)
        y = 1.0 if f.actual_good else 0.0
        total += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return total / len(forecasts)


def calibration_curve(
    forecasts: Sequence[ResolvedForecast], bins: int = DEFAULT_CALIBRATION_BINS
) -> list[CalibrationBin]:
    """Partition forecasts into probability bins → the reliability curve.

    Each forecast falls in bin ``min(floor(p·bins), bins-1)`` (so ``p==1.0``
    lands in the top bin, not a phantom overflow bin). Only *non-empty* bins are
    returned, sorted by index — an empty bin carries no evidence and padding the
    curve with zero-population points would misrepresent the diagram. Empty input
    yields ``[]``.
    """
    n_bins = max(1, bins)
    buckets: dict[int, list[ResolvedForecast]] = defaultdict(list)
    for f in forecasts:
        idx = int(f.predicted_good * n_bins)
        idx = min(max(idx, 0), n_bins - 1)
        buckets[idx].append(f)
    curve: list[CalibrationBin] = []
    for idx in sorted(buckets):
        items = buckets[idx]
        mean_conf = sum(x.predicted_good for x in items) / len(items)
        empirical = sum(1 for x in items if x.actual_good) / len(items)
        curve.append(CalibrationBin(idx, mean_conf, empirical, len(items)))
    return curve


def calibration_error(
    forecasts: Sequence[ResolvedForecast], bins: int = DEFAULT_CALIBRATION_BINS
) -> float | None:
    """Expected calibration error — the scalar summary of the reliability curve.

    The population-weighted mean gap between stated confidence and empirical
    rate: ``sum_bin (n_bin / N) · |mean_confidence - empirical_rate|``. 0 means
    perfectly calibrated (every bin on the diagonal); larger means the stated
    confidences systematically miss the truth. ``None`` for an empty set. This is
    the *calibration* axis, reported alongside — never merged with —
    :func:`discrimination`.
    """
    if not forecasts:
        return None
    curve = calibration_curve(forecasts, bins=bins)
    n_total = len(forecasts)
    return sum(
        (b.n / n_total) * abs(b.mean_confidence - b.empirical_rate) for b in curve
    )


def discrimination(forecasts: Sequence[ResolvedForecast]) -> float | None:
    """Area under the ROC curve — does the judge separate good from bad at all?

    The rank statistic ``P(predicted_good(good) > predicted_good(bad))`` with
    ties counted as half (the Mann-Whitney U form of AUC): over every
    good/bad pair, the fraction where the judge ranked the good change higher.
    0.5 is no better than a coin flip; 1.0 is perfect separation; below 0.5 is
    *inverted* (the judge is anti-discriminating — its ordering is backwards).

    Returns ``None`` — undefined, not 0.5 — when the outcomes are all-good or
    all-bad: with no contrast there is no separability to measure, and reporting
    0.5 would fake a signal. Callers read ``None`` as "not enough outcome
    diversity yet". This is orthogonal to :func:`calibration_error`: a judge can
    discriminate perfectly (AUC 1.0) while being badly miscalibrated.
    """
    goods = [f.predicted_good for f in forecasts if f.actual_good]
    bads = [f.predicted_good for f in forecasts if not f.actual_good]
    if not goods or not bads:
        return None
    wins = 0.0
    for g in goods:
        for b in bads:
            if g > b:
                wins += 1.0
            elif g == b:
                wins += 0.5
    return wins / (len(goods) * len(bads))


def score_judge(
    judge_id: str,
    judge_family: str,
    resolved: Sequence[ResolvedForecast],
) -> JudgeScore:
    """Aggregate one judge's resolved forecasts into a :class:`JudgeScore`.

    Degenerate honestly: zero resolved → every scalar ``None`` and both
    ``low_confidence`` and ``discrimination_undefined`` set (the "no data yet"
    row the panel renders). Otherwise computes both proper scores, the
    calibration curve + its error, and the discrimination AUC, marking
    ``low_confidence`` on a thin sample and ``discrimination_undefined`` when the
    AUC is undefined (all-same-outcome).
    """
    n = len(resolved)
    if n == 0:
        return JudgeScore(
            judge_id=judge_id,
            judge_family=judge_family,
            n_resolved=0,
            brier=None,
            log_score=None,
            calibration_error=None,
            calibration_bins=(),
            discrimination=None,
            low_confidence=True,
            discrimination_undefined=True,
        )
    disc = discrimination(resolved)
    return JudgeScore(
        judge_id=judge_id,
        judge_family=judge_family,
        n_resolved=n,
        brier=brier_score(resolved),
        log_score=log_score(resolved),
        calibration_error=calibration_error(resolved),
        calibration_bins=tuple(calibration_curve(resolved)),
        discrimination=disc,
        low_confidence=n < MIN_CONFIDENT_RESOLVED,
        discrimination_undefined=disc is None,
    )


def score_all(
    verdicts: Sequence[JudgeVerdictRecord], outcomes: Sequence[Outcome]
) -> list[JudgeScore]:
    """Resolve + score every judge present in *verdicts*, one row each.

    Judges are enumerated from the verdict ledger (not a fixed catalog), so a
    judge with recorded verdicts but *none* resolved yet still gets a row (a "no
    data yet" :class:`JudgeScore` with ``n_resolved == 0``). Rows are sorted by
    ``judge_id`` for a stable panel order.
    """
    resolved = resolve(verdicts, outcomes)
    families: dict[str, str] = {}
    for v in verdicts:
        families.setdefault(v.judge_id, v.judge_family)
    by_judge: dict[str, list[ResolvedForecast]] = defaultdict(list)
    for rf in resolved:
        by_judge[rf.judge_id].append(rf)
    return [
        score_judge(judge_id, families[judge_id], by_judge.get(judge_id, []))
        for judge_id in sorted(families)
    ]


# --- outcome resolution seam (injected) ---------------------------------------


class _EscapeLike(Protocol):
    """Structural view of an escape row — only the join field is needed."""

    @property
    def originating_pr(self) -> int | None: ...


def escaped_subjects(escapes: Iterable[_EscapeLike]) -> set[str]:
    """Subject ids that carry an attributed escape → known-bad outcomes.

    Duck-typed on ``originating_pr`` so the pure engine never imports the escape
    package. An escape with no resolved originating PR (``None``) cannot be
    joined to a subject and is skipped — honest, not force-attributed.
    """
    return {
        subject_for_pr(e.originating_pr)
        for e in escapes
        if e.originating_pr is not None
    }


def resolve_outcomes(
    verdicts: Sequence[JudgeVerdictRecord],
    escaped: set[str],
    *,
    now: datetime,
    grace_window: timedelta = DEFAULT_GRACE_WINDOW,
) -> list[Outcome]:
    """Resolve each verdicted subject to a good/bad/unresolved outcome (pure).

    One outcome per distinct subject:

    * subject in *escaped* → ``good=False`` **immediately** (an escape is
      definitive; no waiting).
    * else, if the subject's *latest* verdict is older than *grace_window* →
      ``good=True`` (it stayed escape-free long enough to trust).
    * else → **unresolved**, omitted (too recent — an escape could still surface).

    The grace window is measured from the *latest* verdict on the subject (the
    most conservative reference — retries on one change span minutes while the
    window spans days, so the choice is immaterial in practice but stated).
    """
    latest_by_subject: dict[str, datetime] = {}
    for v in verdicts:
        prev = latest_by_subject.get(v.subject_id)
        if prev is None or v.recorded_at > prev:
            latest_by_subject[v.subject_id] = v.recorded_at
    outcomes: list[Outcome] = []
    for subject_id, latest in latest_by_subject.items():
        if subject_id in escaped:
            outcomes.append(Outcome(subject_id, good=False))
        elif now - latest > grace_window:
            outcomes.append(Outcome(subject_id, good=True))
        # else: unresolved — omit
    return outcomes


class OutcomeResolver(Protocol):
    """The injected seam that resolves verdicted subjects to ground-truth outcomes.

    Real implementations read an outcome source (the escape ledger); tests inject
    a fake returning canned outcomes. The engine only ever consumes the returned
    :class:`Outcome` list, so it stays pure.
    """

    def resolve(self, verdicts: Sequence[JudgeVerdictRecord]) -> list[Outcome]:
        """Return the resolvable outcomes for *verdicts* (unresolved omitted)."""
        ...


class EscapeLedgerOutcomeResolver:
    """Resolve outcomes from escape records — the production :class:`OutcomeResolver`.

    A thin, *data-in* adapter: it is constructed with the escape records already
    read from the ledger (never the ledger file itself), so the endpoint owns the
    I/O and this class stays pure and unit-testable with synthetic escapes. A
    subject with an attributed escape resolves bad; an escape-free subject past
    the grace window resolves good; a too-recent one is omitted.
    """

    def __init__(
        self,
        escapes: Iterable[_EscapeLike],
        *,
        now: datetime,
        grace_window: timedelta = DEFAULT_GRACE_WINDOW,
    ) -> None:
        self._escaped = escaped_subjects(escapes)
        self._now = now
        self._grace_window = grace_window

    def resolve(self, verdicts: Sequence[JudgeVerdictRecord]) -> list[Outcome]:
        return resolve_outcomes(
            verdicts, self._escaped, now=self._now, grace_window=self._grace_window
        )


# --- ledger (append-only) ------------------------------------------------------


def judge_verdict_ledger_path(data_root: Path) -> Path:
    """Return ``<data_root>/calibration/judge_verdicts.jsonl``."""
    return data_root / CALIBRATION_SUBDIR / VERDICTS_FILENAME


class JudgeCalibrationLedger:
    """Append-only judge-verdict ledger over one ``judge_verdicts.jsonl``.

    Reuses the shared :class:`jsonl_ledger.AppendOnlyJsonlLedger` I/O; a missing
    file reads as empty. Rows are never deduplicated or rewritten — the same
    judge may verdict the same subject across retries, and each is its own datum.
    """

    def __init__(self, path: Path) -> None:
        self._ledger: AppendOnlyJsonlLedger[JudgeVerdictRecord] = AppendOnlyJsonlLedger(
            path, JudgeVerdictRecord, logger=logger
        )

    @property
    def path(self) -> Path:
        return self._ledger.path

    def record(self, record: JudgeVerdictRecord) -> None:
        """Append one verdict row (creating the dir/file if needed)."""
        self._ledger.append(record)

    def read_all(self) -> list[JudgeVerdictRecord]:
        """Every recorded verdict, oldest first; ``[]`` when absent."""
        return self._ledger.read_all()


# --- fail-soft recorder (the load-bearing wiring seam) -------------------------


def record_verdict(
    ledger_path: Path,
    *,
    judge_id: str,
    judge_family: str,
    subject_id: str,
    verdict: Verdict,
    confidence: float,
    recorded_at: datetime,
) -> bool:
    """Best-effort append of one judge verdict — NEVER raises.

    The recording call is wired into load-bearing review code (the
    PostVerifyAdvisor emit site), where a calibration-ledger write failure must
    be completely invisible to the verdict it is observing: it can never change
    the verdict, delay it, or raise into the review pipeline. Any exception is
    swallowed and logged; the return value (``True`` on a successful append) is
    for tests, not control flow.
    """
    try:
        JudgeCalibrationLedger(ledger_path).record(
            JudgeVerdictRecord(
                judge_id=judge_id,
                judge_family=judge_family,
                subject_id=subject_id,
                verdict=verdict,
                confidence=confidence,
                recorded_at=recorded_at,
            )
        )
        return True
    except Exception:  # noqa: BLE001 — fail-soft: observing must never break review
        logger.warning(
            "judge-calibration: verdict recording failed (judge_id=%s subject=%s)",
            judge_id,
            subject_id,
            exc_info=True,
        )
        return False
