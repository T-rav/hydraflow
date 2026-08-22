"""Test-adequacy gate calibration — is the gate's strictness earned? (#11593 seam 2)

The August-2026 manifest audit (#11593) found the test-adequacy gate killed
**61 of 105 failed implement runs**, 23 of them by the *independent verifier
overriding an OK verdict*. Seams 1 and 3 (#11603) made the gate repair in-run
and made the failure split visible. This is seam 2: the instrument that asks
whether those rejections were **right**.

Fourth in the "measure the factory's own quality machinery" family and a direct
application of ADR-0127 (judge calibration): the mutation gauntlet (#10835)
measures *gate sensitivity*, the finder calibration (#10821) measures *finder
noise*, judge calibration (#10836) measures *judge quality in the abstract* —
this one points that engine at ONE judge, the test-adequacy verifier, and
reports what the available evidence can and cannot establish about it.

Same house shape as its siblings: **pure core, no I/O** (the loader lives in
``scripts/calibrate_adequacy_gate.py``), an **injected ground-truth seam** (the
caller supplies :class:`IssueOutcome` rows built from the escape ledger), and
**honest degeneracy** — nothing here fabricates a label it cannot derive.

The load-bearing methodological ruling
--------------------------------------

**A gate's rejections are outcome-censored: the reject arm is not identifiable
from the escape ledger.** The escape ledger keys defects to an ``originating_pr``
— it observes only *merged* work. A run the gate rejects never merges, so no
escape can ever be attributed to it, and no amount of waiting will produce one.
Feeding rejections through :func:`judge_calibration.resolve` therefore yields
*zero* resolved forecasts by construction — which is why :func:`to_judge_verdicts`
deliberately keys rejections with :func:`judge_calibration.subject_for_issue`
(the helper whose own docstring says it "will not resolve against the escape
ledger"): the censoring is made visible in the report rather than papered over.

This is the classic **selective-labels** problem, and it means the honest answer
to "what is the verifier's precision?" is *not yet determined*. Rather than
invent a label, this engine reports the four things that ARE derivable and
states plainly which of them can and cannot support a strictness change:

1. **Accept-arm proper score** (:attr:`CalibrationReport.accept_arm_score`) —
   runs the gate *passed*, joined to the escape ledger via
   :func:`judge_calibration.score_judge`. Measures how often accepted work
   escapes, i.e. whether the gate is too *loose*. Biased by the same selection
   (only passed work is observed), so it is reported with
   :attr:`Identifiability.under_determined` alongside, never alone — and an
   escape-free reading only counts once it has aged past ADR-0127's
   escape-detection grace window (:func:`resolved_escapes`), because a merge
   from an hour ago has had no chance to accumulate an escape and scoring it
   clean would credit the gate for work nothing has checked.
2. **Recovery** — did the gated issue reach a *later successful run*? A demand
   nobody ever satisfies costs the full attempt budget whether or not it was
   correct, so this is the cost axis, not a correctness axis.
3. **Demand stationarity** (:func:`demand_stationarity`) — when the same issue
   is rejected twice, do the two rejections demand the *same* thing? Fully
   disjoint successive demands mean the gate is not holding a fixed bar; it is
   resampling from an unbounded space of possible gaps, and no finite amount of
   test-writing satisfies it. This needs **no ground truth at all** and is the
   strongest over-strictness evidence the corpus can carry.
4. **Finding taxonomy** (:func:`grade_finding`, :func:`is_out_of_remit`) — is a
   rejection anchored in demonstrated survivability (a mutant that lives, a
   revert the suite does not catch), in a named code referent, or in nothing
   locatable at all? And does it demand something the gate does not own (dead
   code, a contract mismatch)? An unanchored demand is the one the #11603
   repair loop cannot act on: it hands the finding text back to the implementer.

Since #11644 the live gate enforces the same two properties, so (3) and (4) are
also this instrument's **acceptance test** — the numbers it prints are what the
change has to move:

* :func:`demand_anchoring` — the anchored share of the gate's findings.
  #11643 measured 97 of 129 (75 %) with no referent at all. The predicate is
  imported from ``adequacy_demand``, the module the runtime enforces with, so
  there is exactly one definition of "anchored" and the measurement cannot
  drift from the enforcement.
* :func:`pinned_demand_overlap` — the retry overlap read off the pin the gate
  actually carried onto the retry, rather than inferred from consecutive
  rejections. A corpus with no pinned run reports "not enforced", never a
  fabricated score.

Everything in (3) and (4) is a **lexical proxy for the justification's quality**,
NOT proof the rejection was wrong. :class:`SuspectRejection` is named for that:
these are rejections whose stated reason is weak *on its face* and which a human
should read — not a labelled error set.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from adequacy_demand import (
    cites_demonstration,
    demand_tokens,
    is_anchored,
    names_referent,
    split_findings,
)
from implement_failure_class import classify_implement_failure
from judge_calibration import (
    DEFAULT_GRACE_WINDOW,
    JudgeScore,
    JudgeVerdictRecord,
    Outcome,
    Verdict,
    resolve,
    score_judge,
    subject_for_issue,
    subject_for_pr,
)

logger = logging.getLogger(__name__)

# --- identity + constants -------------------------------------------------------

#: The judge this instrument scores, in ``judge_calibration``'s namespace.
JUDGE_ID = "test-adequacy-gate"
JUDGE_FAMILY = "implement-gate"

#: Verdict sources, mirroring ``models.TestAdequacyOutcome.verdict_source``.
VERDICT_SOURCE_LLM_FAIL = "llm-fail"
VERDICT_SOURCE_VERIFIER_OVERRIDE = "verifier-override"
VERDICT_SOURCE_COVERAGE_DELTA = "coverage-delta"
VERDICT_SOURCES: tuple[str, ...] = (
    VERDICT_SOURCE_LLM_FAIL,
    VERDICT_SOURCE_VERIFIER_OVERRIDE,
    VERDICT_SOURCE_COVERAGE_DELTA,
)

#: Manifest error prefixes. Pinned by ``tests/regressions/`` on the #11603 side —
#: downstream tooling (this instrument included) greps them.
REJECTION_PREFIX = "test-adequacy failed:"
OVERRIDE_PREFIX = "Independent verifier overrode OK:"

#: The failure class ``implement_failure_class`` assigns to a gate rejection.
ADEQUACY_FAILURE_CLASS = "test_adequacy"

#: A binary verdict is a forecast at p in {0, 1}. The adequacy verifier states no
#: confidence, so the bridge to ``judge_calibration`` records 1.0 and the Brier
#: score degenerates to a plain error rate — honest and documented, rather than
#: fabricating a mid-range confidence the judge never expressed. The LOG score is
#: uninformative under this mapping (it is dominated by the eps clip), which is
#: why the report reads the Brier and leaves the log score to the raw JudgeScore.
BINARY_VERDICT_CONFIDENCE = 1.0

#: Two-sided 95% normal quantile for the Wilson score interval.
DEFAULT_Z = 1.959963984540054


class GateOutcome(StrEnum):
    """What the test-adequacy gate did on one implement run."""

    #: The run cleared the gate (the implement run succeeded).
    ACCEPTED = "accepted"
    #: The gate rejected the run — ``test-adequacy failed: ...``.
    REJECTED = "rejected"
    #: The run died before/elsewhere (timeout, zero-commit, diff-sanity, quality).
    NOT_REACHED = "not-reached"


class RecordShape(StrEnum):
    """Which manifest shape a record was parsed from.

    The corpus spans the #11603 boundary: older manifests carry only an
    ``error`` string, newer ones carry a structured ``test_adequacy`` block.
    Reported so a thin structured slice is never mistaken for the whole corpus.
    """

    LEGACY = "legacy"
    STRUCTURED = "structured"


class EvidenceGrade(StrEnum):
    """How well anchored one finding's demand is — a proxy, not a verdict."""

    #: Cites a concrete survivability demonstration: a mutant that lives, a
    #: revert the suite does not catch, a regression shown silent.
    DEMONSTRATED = "demonstrated"
    #: Names a concrete referent — a symbol, path, constant, flag, or route.
    NAMED_GAP = "named-gap"
    #: Names no code referent at all ("missing-error-path-coverage") — the
    #: demand cannot be mechanically located in the diff from its own text.
    UNANCHORED = "unanchored"


class SuspectReason(StrEnum):
    """Why a rejection's stated justification reads weak on its face."""

    ALL_FINDINGS_UNANCHORED = "all-findings-unanchored"
    DEMAND_NOT_STATIONARY = "demand-not-stationary"
    SELF_DECLARED_CORE_COVERED = "self-declared-core-covered"
    REMIT_DRIFT = "remit-drift"


# --- records --------------------------------------------------------------------


@dataclass(frozen=True)
class AdequacyRunRecord:
    """One implement run, viewed through the test-adequacy gate."""

    issue_number: int
    recorded_at: datetime
    gate_outcome: GateOutcome
    verdict_source: str | None = None
    findings: tuple[str, ...] = ()
    duration_seconds: float = 0.0
    repair_passes_used: int = 0
    shape: RecordShape = RecordShape.LEGACY
    #: The demand the PREVIOUS attempt stated, carried onto this one (#11644).
    #: Empty for every pre-#11644 run — the instrument reports "not enforced"
    #: rather than a fabricated 0, so before/after stays legible.
    pinned_findings: tuple[str, ...] = ()
    #: Findings this attempt raised that the pinned demand never mentioned.
    new_findings: tuple[str, ...] = ()
    #: Findings recorded but NOT blocking (new *and* unanchored on a pinned
    #: retry). The non-stationarity the pin absorbs, kept visible.
    advisory_findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class IssueOutcome:
    """Injected ground truth for one issue — the escape-ledger join, data-in.

    ``escaped`` is ``None`` when the escape ledger could not be consulted at all
    (no closing PR known, or no ledger). ``None`` is never silently read as
    "clean": an unresolvable outcome is dropped from every rate and counted in
    :class:`Identifiability` instead.

    ``escaped=False`` is a *reading*, not yet a resolution. ``closed_at`` — when
    the closing work landed — is what turns it into one, because escapes surface
    with a lag (ADR-0127 ``DEFAULT_GRACE_WINDOW``): a PR that merged an hour ago
    has had no chance to accumulate one, so calling it clean would credit the
    gate for work nothing has checked yet. :func:`resolved_escapes` therefore
    holds a clean reading unresolved until ``closed_at`` clears the grace window,
    and treats a missing ``closed_at`` as unresolvable rather than as aged.
    An escape that *did* surface resolves bad immediately — no wait.
    """

    issue_number: int
    closing_prs: tuple[int, ...] = ()
    escaped: bool | None = None
    closed_at: datetime | None = None


@dataclass(frozen=True)
class ProportionInterval:
    """A proportion with its Wilson score interval — ``k`` of ``n``."""

    k: int
    n: int
    point: float
    low: float
    high: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "n": self.n,
            "point": self.point,
            "low": self.low,
            "high": self.high,
        }


@dataclass(frozen=True)
class DemandStationarity:
    """Do successive rejections of one issue demand the *same* thing?

    ``mean_jaccard`` near 1.0 means the gate holds a fixed bar across retries;
    near 0.0 means every retry faces a fresh, previously unmentioned demand.
    ``None`` when no issue was rejected twice (nothing to compare).
    ``disjoint_rate`` is the same count with its Wilson interval, because the
    repeat-pair denominator is always small.
    """

    n_repeat_pairs: int
    n_disjoint_pairs: int
    mean_jaccard: float | None
    disjoint_rate: ProportionInterval | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "n_repeat_pairs": self.n_repeat_pairs,
            "n_disjoint_pairs": self.n_disjoint_pairs,
            "mean_jaccard": self.mean_jaccard,
            "disjoint_rate": (
                self.disjoint_rate.to_json_dict() if self.disjoint_rate else None
            ),
        }


@dataclass(frozen=True)
class DemandAnchoring:
    """How much of the gate's demand names something locatable (#11644).

    The headline number the anchoring rule moves: #11643 measured **97 of 129
    findings (75 %) with no code referent at all**, which is what the seam-1
    repair loop was being handed as "write exactly these missing tests".
    ``anchored_share`` is that number's complement, with a Wilson interval;
    ``n_fully_unanchored_rejections`` counts rejections where *nothing* the
    gate demanded could be located.
    """

    n_findings: int
    n_anchored: int
    anchored_share: ProportionInterval | None
    n_rejections: int
    n_fully_unanchored_rejections: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "n_findings": self.n_findings,
            "n_anchored": self.n_anchored,
            "anchored_share": (
                self.anchored_share.to_json_dict() if self.anchored_share else None
            ),
            "n_rejections": self.n_rejections,
            "n_fully_unanchored_rejections": self.n_fully_unanchored_rejections,
        }


@dataclass(frozen=True)
class PinnedDemandOverlap:
    """Retry overlap measured against the demand that was actually PINNED (#11644).

    :class:`DemandStationarity` infers the moving bar from consecutive
    rejections; this measures it directly, from the pin the gate carried onto
    the retry. ``n_pinned_runs == 0`` means no run in the corpus enforced a
    pin — the pre-#11644 state, reported as "not enforced" rather than as a
    perfect or a zero score.

    Counted over runs of **either** outcome, not rejections only: a retry the
    pin *waived* is the case where the demand moved furthest, so scoring only
    the retries that still failed would bias the overlap upward and hide
    exactly what the metric exists to show.

    ``n_advisory_findings`` is the count the pin absorbed: findings that were
    both new *and* unanchored, recorded instead of rejecting the run.
    """

    n_pinned_runs: int
    n_disjoint: int
    mean_jaccard: float | None
    disjoint_rate: ProportionInterval | None
    n_new_findings: int
    n_advisory_findings: int

    @property
    def enforced(self) -> bool:
        """Did any run in this corpus carry a pinned demand?"""
        return self.n_pinned_runs > 0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "n_pinned_runs": self.n_pinned_runs,
            "n_disjoint": self.n_disjoint,
            "mean_jaccard": self.mean_jaccard,
            "disjoint_rate": (
                self.disjoint_rate.to_json_dict() if self.disjoint_rate else None
            ),
            "n_new_findings": self.n_new_findings,
            "n_advisory_findings": self.n_advisory_findings,
            "enforced": self.enforced,
        }


@dataclass(frozen=True)
class SuspectRejection:
    """A rejection whose stated justification is weak — a read-me, not a label."""

    issue_number: int
    recorded_at: datetime
    verdict_source: str | None
    reasons: tuple[SuspectReason, ...]
    findings: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "issue_number": self.issue_number,
            "recorded_at": self.recorded_at.isoformat(),
            "verdict_source": self.verdict_source,
            "reasons": [r.value for r in self.reasons],
            "findings": list(self.findings),
        }


@dataclass(frozen=True)
class VerdictSourceSummary:
    """Everything derivable about one verdict source's rejections.

    ``post_rework_escape`` is the escape rate of the work that **eventually
    merged** for these issues. It is NOT the rejected diff's outcome (that diff
    never merged — see the module docstring); it asks the weaker question
    "after the gate sent this issue back, did the thing that finally landed
    still escape?". Read it as a bound on how much defect reduction the
    rejection bought, never as the rejection's precision.
    """

    verdict_source: str
    n_rejections: int
    n_issues: int
    recovery: ProportionInterval | None
    post_rework_escape: ProportionInterval | None
    demonstrated_share: ProportionInterval | None
    evidence_mix: Mapping[EvidenceGrade, int]
    n_suspect: int
    median_cost_minutes: float | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "verdict_source": self.verdict_source,
            "n_rejections": self.n_rejections,
            "n_issues": self.n_issues,
            "recovery": self.recovery.to_json_dict() if self.recovery else None,
            "post_rework_escape": (
                self.post_rework_escape.to_json_dict()
                if self.post_rework_escape
                else None
            ),
            "demonstrated_share": (
                self.demonstrated_share.to_json_dict()
                if self.demonstrated_share
                else None
            ),
            "evidence_mix": {g.value: n for g, n in self.evidence_mix.items()},
            "n_suspect": self.n_suspect,
            "median_cost_minutes": self.median_cost_minutes,
        }


@dataclass(frozen=True)
class Identifiability:
    """What the corpus can and cannot establish — the honesty header.

    ``under_determined`` is the headline: ``True`` means no strictness change is
    supportable from this data, whatever the point estimates say.
    """

    n_rejections: int
    n_rejections_resolved: int
    n_acceptances: int
    n_acceptances_resolved: int
    under_determined: bool
    reasons: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "n_rejections": self.n_rejections,
            "n_rejections_resolved": self.n_rejections_resolved,
            "n_acceptances": self.n_acceptances,
            "n_acceptances_resolved": self.n_acceptances_resolved,
            "under_determined": self.under_determined,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class CalibrationReport:
    """The instrument's output — read ``identifiability`` before any rate."""

    window_start: datetime | None
    window_end: datetime | None
    n_runs: int
    n_accepted: int
    n_rejected: int
    n_not_reached: int
    n_structured: int
    median_rejection_minutes: float | None
    rejection_hours: float
    by_verdict_source: tuple[VerdictSourceSummary, ...]
    stationarity: DemandStationarity
    #: #11644 acceptance metrics — the anchored share of the demand, and the
    #: retry overlap measured against the pin the gate actually carried.
    anchoring: DemandAnchoring
    pinned_demand: PinnedDemandOverlap
    accept_arm_score: JudgeScore
    identifiability: Identifiability
    suspect_rejections: tuple[SuspectRejection, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start.isoformat()
            if self.window_start
            else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "n_runs": self.n_runs,
            "n_accepted": self.n_accepted,
            "n_rejected": self.n_rejected,
            "n_not_reached": self.n_not_reached,
            "n_structured": self.n_structured,
            "median_rejection_minutes": self.median_rejection_minutes,
            "rejection_hours": self.rejection_hours,
            "by_verdict_source": [s.to_json_dict() for s in self.by_verdict_source],
            "stationarity": self.stationarity.to_json_dict(),
            "anchoring": self.anchoring.to_json_dict(),
            "pinned_demand": self.pinned_demand.to_json_dict(),
            "accept_arm_score": self.accept_arm_score.to_json_dict(),
            "identifiability": self.identifiability.to_json_dict(),
            "suspect_rejections": [s.to_json_dict() for s in self.suspect_rejections],
        }


# --- manifest parsing (tolerant) ------------------------------------------------

_COMPACT_TIMESTAMP = re.compile(r"^(\d{8})T(\d{6})Z$")


def parse_run_timestamp(raw: object) -> datetime | None:
    """Parse a manifest timestamp; ``None`` when unparseable — never raises.

    Run directories are named ``YYYYMMDDTHHMMSSZ``; structured payloads may carry
    an ISO-8601 string instead. Both are accepted and normalised to UTC-aware.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    compact = _COMPACT_TIMESTAMP.match(text)
    if compact:
        # The trailing "Z" is stripped by the pattern, so re-attach an explicit
        # UTC offset and parse with %z — that keeps the result tz-aware without
        # a naive intermediate.
        try:
            return datetime.strptime(
                f"{compact.group(1)}{compact.group(2)}+0000", "%Y%m%d%H%M%S%z"
            )
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def strip_rejection_prefix(error: str) -> tuple[str, str]:
    """Split a rejection error into ``(verdict_source, summary)``.

    Legacy manifests encode the verdict source in the message: an
    ``Independent verifier overrode OK:`` prefix inside the rejection means the
    independent verifier vetoed a passing finder verdict; anything else is the
    finder's own fail. The deterministic coverage-delta source is not
    distinguishable in the legacy shape — it only arrives with #11603's
    structured block, so it is never *guessed* here.
    """
    summary = error.split(REJECTION_PREFIX, 1)[-1].strip()
    if summary.startswith(OVERRIDE_PREFIX):
        return VERDICT_SOURCE_VERIFIER_OVERRIDE, summary[len(OVERRIDE_PREFIX) :].strip()
    return VERDICT_SOURCE_LLM_FAIL, summary


def _coerce_findings(raw: object) -> tuple[str, ...]:
    """Keep only non-empty string findings from a structured block."""
    if not isinstance(raw, list):
        return ()
    return tuple(item.strip() for item in raw if isinstance(item, str) and item.strip())


def parse_run_manifest(raw: object) -> AdequacyRunRecord | None:
    """Parse one run manifest into a record; ``None`` when malformed.

    Handles BOTH corpus shapes. The structured ``test_adequacy`` block (#11603)
    supplies verdict source, findings and repair passes when present; otherwise
    they are recovered from the legacy ``error`` string via
    :func:`strip_rejection_prefix` + :func:`split_findings`. A manifest missing
    an issue number or a parseable timestamp is dropped, not guessed — a corpus
    walk must survive a truncated write without losing the rest of the run.
    """
    if not isinstance(raw, Mapping):
        return None
    issue_raw = raw.get("issue_number")
    if not isinstance(issue_raw, int) or isinstance(issue_raw, bool):
        return None
    recorded_at = parse_run_timestamp(raw.get("timestamp"))
    if recorded_at is None:
        return None

    outcome = raw.get("outcome")
    error = raw.get("error")
    error_text = error if isinstance(error, str) else ""
    failure_class = raw.get("failure_class")
    is_rejection = (
        failure_class == ADEQUACY_FAILURE_CLASS
        if isinstance(failure_class, str)
        else classify_implement_failure(error_text) == ADEQUACY_FAILURE_CLASS
    )

    if outcome == "success":
        gate_outcome = GateOutcome.ACCEPTED
    elif outcome == "failed" and is_rejection:
        gate_outcome = GateOutcome.REJECTED
    else:
        gate_outcome = GateOutcome.NOT_REACHED

    verdict_source: str | None = None
    findings: tuple[str, ...] = ()
    if gate_outcome is GateOutcome.REJECTED and error_text:
        verdict_source, summary = strip_rejection_prefix(error_text)
        findings = split_findings(summary)

    block = raw.get("test_adequacy")
    shape = RecordShape.LEGACY
    repair_passes = 0
    pinned: tuple[str, ...] = ()
    new_findings: tuple[str, ...] = ()
    advisory: tuple[str, ...] = ()
    if isinstance(block, Mapping):
        shape = RecordShape.STRUCTURED
        source = block.get("verdict_source")
        if isinstance(source, str) and source in VERDICT_SOURCES:
            verdict_source = source
        # A structured block's findings are AUTHORITATIVE when the key is
        # present, empty list included (#11644). Falling back to the legacy
        # error-string split on an explicit ``[]`` would re-derive a demand the
        # runtime deliberately declined to treat as one: a verifier override
        # that enumerated no gaps records ``findings: []``, and its summary can
        # be pure policy boilerplate ("verifier produced no output (fail-closed
        # policy treats this as an override)"). Splitting that sentence into a
        # finding would inflate the unanchored share this instrument exists to
        # measure — with text that was never a demand. A manifest carrying no
        # ``findings`` key at all still falls back, which is the pre-#11603
        # legacy shape.
        if "findings" in block:
            findings = _coerce_findings(block.get("findings"))
        passes = block.get("repair_passes_used")
        if isinstance(passes, int) and not isinstance(passes, bool):
            repair_passes = max(0, passes)
        # #11644 demand-contract telemetry. Absent on every pre-#11644
        # manifest, which is exactly what "not enforced" must look like.
        pinned = _coerce_findings(block.get("pinned_findings"))
        new_findings = _coerce_findings(block.get("new_findings"))
        advisory = _coerce_findings(block.get("advisory_findings"))

    duration = raw.get("duration_seconds")
    seconds = float(duration) if isinstance(duration, (int, float)) else 0.0

    return AdequacyRunRecord(
        issue_number=issue_raw,
        recorded_at=recorded_at,
        gate_outcome=gate_outcome,
        verdict_source=verdict_source,
        findings=findings,
        duration_seconds=max(0.0, seconds),
        repair_passes_used=repair_passes,
        shape=shape,
        pinned_findings=pinned,
        new_findings=new_findings,
        advisory_findings=advisory,
    )


# --- finding taxonomy (lexical proxies) -----------------------------------------

#: Demands that describe a defect the *test-adequacy* gate does not own.
_OUT_OF_REMIT_NEEDLES: tuple[str, ...] = (
    "dead code",
    "dead new",
    "unused",
    "contract-mismatch",
    "contract mismatch",
    "attacker-controlled",
    "stale-doc",
    "documentation-inconsistency",
    "doc-code-mismatch",
    "scope-creep",
)

#: Any of these makes a finding a genuine test-gap demand, whatever else it says.
_TEST_GAP_NEEDLES: tuple[str, ...] = (
    "test",
    "unpinned",
    "uncovered",
    "coverage",
    "tautological",
    "vacuous",
    "non-discriminating",
    "mutant",
    "mutation",
    "assert",
    "unverified",
    "unexercised",
)

#: The verifier itself conceding the change under test is already covered.
_SELF_DECLARED_COVERED_NEEDLES: tuple[str, ...] = ("fully covered", "confined to")


def grade_finding(finding: str) -> EvidenceGrade:
    """Grade how well anchored one finding is — a proxy for justification quality.

    :attr:`EvidenceGrade.DEMONSTRATED` wins outright: a surviving mutant or a
    revert-safe route is a checkable claim about behaviour. Otherwise a concrete
    referent (symbol, path, constant, flag, route) makes it a
    :attr:`EvidenceGrade.NAMED_GAP`; text naming no code referent at all is
    :attr:`EvidenceGrade.UNANCHORED`. "Unanchored" is a statement about the
    finding's *locatability*, not about whether the gap is real.

    The two predicates live in ``adequacy_demand`` (#11644) because the live
    gate now enforces the same test at its emit site. One definition, two
    readers: what this instrument scores is exactly what the runtime demands.
    """
    if cites_demonstration(finding):
        return EvidenceGrade.DEMONSTRATED
    if names_referent(finding):
        return EvidenceGrade.NAMED_GAP
    return EvidenceGrade.UNANCHORED


def is_out_of_remit(finding: str) -> bool:
    """Does this finding demand something other than a test?

    A finding that names a non-test defect (dead code, a contract mismatch, a
    doc inconsistency) *and* says nothing about a missing test is scope drift by
    the gate: the right disposition is a separate finding, not a rejected run.
    Any test-gap phrasing keeps it in remit, so "dead code path is untested" is
    a legitimate adequacy demand.
    """
    lowered = finding.lower()
    if not any(needle in lowered for needle in _OUT_OF_REMIT_NEEDLES):
        return False
    return not any(needle in lowered for needle in _TEST_GAP_NEEDLES)


def _record_tokens(record: AdequacyRunRecord) -> frozenset[str]:
    """Union of every finding's tokens on one rejection."""
    return demand_tokens(record.findings)


# --- statistics (pure) ----------------------------------------------------------


def wilson_interval(k: int, n: int, z: float = DEFAULT_Z) -> ProportionInterval | None:
    """Wilson score interval for ``k`` successes in ``n`` trials.

    Wilson rather than the normal approximation because every rate here has a
    small denominator and often sits near 0 or 1, where the normal interval runs
    outside ``[0, 1]`` and badly under-covers. ``None`` for ``n == 0`` — no
    evidence, not "0.0". Bounds are clamped into the unit interval.
    """
    if n <= 0:
        return None
    p = k / n
    z_sq = z * z
    denom = 1.0 + z_sq / n
    centre = (p + z_sq / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1.0 - p) / n + z_sq / (4 * n * n))
    return ProportionInterval(
        k=k,
        n=n,
        point=p,
        low=max(0.0, centre - margin),
        high=min(1.0, centre + margin),
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard similarity of two token sets; two empty sets count as identical."""
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def demand_stationarity(records: Sequence[AdequacyRunRecord]) -> DemandStationarity:
    """Do successive rejections of one issue demand the same thing?

    Groups rejections by issue, orders them in time, and scores each consecutive
    pair by the Jaccard overlap of its finding tokens. A **disjoint** pair (zero
    overlap) means the second rejection asked for something the first never
    mentioned — the implementer satisfied the stated bar and was rejected
    anyway. This needs no ground truth, which is what makes it the load-bearing
    over-strictness measurement in an outcome-censored corpus.
    """
    by_issue: dict[int, list[AdequacyRunRecord]] = defaultdict(list)
    for record in records:
        if record.gate_outcome is GateOutcome.REJECTED:
            by_issue[record.issue_number].append(record)
    scores: list[float] = []
    for runs in by_issue.values():
        ordered = sorted(runs, key=lambda r: r.recorded_at)
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            scores.append(_jaccard(_record_tokens(earlier), _record_tokens(later)))
    disjoint = sum(1 for s in scores if s == 0.0)
    return DemandStationarity(
        n_repeat_pairs=len(scores),
        n_disjoint_pairs=disjoint,
        mean_jaccard=statistics.fmean(scores) if scores else None,
        disjoint_rate=wilson_interval(disjoint, len(scores)),
    )


def demand_anchoring(records: Sequence[AdequacyRunRecord]) -> DemandAnchoring:
    """How much of the gate's demand names something locatable (#11644).

    The complement of #11643's headline: 97 of 129 findings (75 %) named no
    code referent at all. This is the number the anchoring rule has to move,
    and it needs no ground truth — same property that makes
    :func:`demand_stationarity` the load-bearing measurement in an
    outcome-censored corpus.
    """
    rejections = [r for r in records if r.gate_outcome is GateOutcome.REJECTED]
    findings = [f for r in rejections for f in r.findings]
    n_anchored = sum(1 for f in findings if is_anchored(f))
    fully_unanchored = sum(
        1
        for r in rejections
        if r.findings and not any(is_anchored(f) for f in r.findings)
    )
    return DemandAnchoring(
        n_findings=len(findings),
        n_anchored=n_anchored,
        anchored_share=wilson_interval(n_anchored, len(findings)),
        n_rejections=len(rejections),
        n_fully_unanchored_rejections=fully_unanchored,
    )


def pinned_demand_overlap(
    records: Sequence[AdequacyRunRecord],
) -> PinnedDemandOverlap:
    """Retry overlap against the demand the gate actually pinned (#11644).

    :func:`demand_stationarity` *infers* the moving bar by pairing consecutive
    rejections; this reads the pin the run carried and compares it with what
    that run then demanded. A corpus where nothing enforced a pin reports
    ``n_pinned_runs=0`` and ``mean_jaccard=None`` — "not enforced", never a
    fabricated score.

    Runs of either outcome count: a retry the pin *waived* still stated a
    demand (its absorbed findings ride ``findings``), and it is the case where
    the bar moved furthest, so restricting the denominator to rejections would
    bias the overlap upward.

    Two exclusions, both "not comparable" rather than "no overlap":

    * a run that stated no findings — there is nothing to compare with the pin;
    * a pin carrying no topical tokens of its own (short symbol names only) —
      a Jaccard of 0.0 against it would read as "demanded something entirely
      new" when the truth is "cannot discriminate". The live gate treats that
      same case as "no pin in force" and blocks on every finding, so the
      exclusion matches what actually happened.
    """
    pinned_runs = [
        r
        for r in records
        if r.pinned_findings and r.findings and demand_tokens(r.pinned_findings)
    ]
    scores = [
        _jaccard(demand_tokens(r.pinned_findings), demand_tokens(r.findings))
        for r in pinned_runs
    ]
    disjoint = sum(1 for s in scores if s == 0.0)
    return PinnedDemandOverlap(
        n_pinned_runs=len(pinned_runs),
        n_disjoint=disjoint,
        mean_jaccard=statistics.fmean(scores) if scores else None,
        disjoint_rate=wilson_interval(disjoint, len(scores)),
        n_new_findings=sum(len(r.new_findings) for r in pinned_runs),
        n_advisory_findings=sum(len(r.advisory_findings) for r in records),
    )


# --- suspect rejections ---------------------------------------------------------


def suspect_rejections(
    records: Sequence[AdequacyRunRecord],
) -> tuple[SuspectRejection, ...]:
    """Rejections whose stated justification is weak on its face.

    NOT a labelled error set — the corpus cannot label a rejection wrong (see the
    module docstring). These are the rows a human should read first: an
    all-unanchored demand names nothing locatable; a demand disjoint from the previous
    rejection of the same issue moved the target; a self-declared "the fix itself
    is fully covered" concedes the change under test was adequate; an
    out-of-remit demand asks for something the gate does not own.
    """
    previous_tokens: dict[int, frozenset[str]] = {}
    suspects: list[SuspectRejection] = []
    for record in sorted(records, key=lambda r: (r.recorded_at, r.issue_number)):
        if record.gate_outcome is not GateOutcome.REJECTED:
            continue
        tokens = _record_tokens(record)
        reasons: list[SuspectReason] = []
        grades = [grade_finding(f) for f in record.findings]
        if grades and all(g is EvidenceGrade.UNANCHORED for g in grades):
            reasons.append(SuspectReason.ALL_FINDINGS_UNANCHORED)
        prior = previous_tokens.get(record.issue_number)
        if prior is not None and not (prior & tokens):
            reasons.append(SuspectReason.DEMAND_NOT_STATIONARY)
        blob = " ".join(record.findings).lower()
        if any(needle in blob for needle in _SELF_DECLARED_COVERED_NEEDLES):
            reasons.append(SuspectReason.SELF_DECLARED_CORE_COVERED)
        if any(is_out_of_remit(f) for f in record.findings):
            reasons.append(SuspectReason.REMIT_DRIFT)
        previous_tokens[record.issue_number] = tokens
        if reasons:
            suspects.append(
                SuspectRejection(
                    issue_number=record.issue_number,
                    recorded_at=record.recorded_at,
                    verdict_source=record.verdict_source,
                    reasons=tuple(reasons),
                    findings=record.findings,
                )
            )
    return tuple(suspects)


# --- bridge to judge_calibration (ADR-0127) -------------------------------------


def to_judge_verdicts(
    records: Sequence[AdequacyRunRecord], outcomes: Sequence[IssueOutcome]
) -> list[JudgeVerdictRecord]:
    """Map gate decisions onto ``judge_calibration``'s verdict ledger shape.

    An acceptance is a ``PASS`` keyed to the issue's closing PR
    (:func:`judge_calibration.subject_for_pr`) so it joins to the escape ledger.
    A rejection is a ``FAIL`` keyed to the *issue*
    (:func:`judge_calibration.subject_for_issue`) — deliberately, because the
    rejected work never merged and therefore has no escape-joinable subject.
    That is the censoring, expressed in the data rather than argued in prose:
    :func:`judge_calibration.resolve` drops every rejection, and
    :class:`Identifiability` reports the zero.

    Runs that never reached the gate contribute no verdict.
    """
    pr_by_issue = {
        outcome.issue_number: outcome.closing_prs[0]
        for outcome in outcomes
        if outcome.closing_prs
    }
    verdicts: list[JudgeVerdictRecord] = []
    for record in records:
        if record.gate_outcome is GateOutcome.ACCEPTED:
            pr = pr_by_issue.get(record.issue_number)
            subject = (
                subject_for_pr(pr)
                if pr is not None
                else subject_for_issue(record.issue_number)
            )
            verdict = Verdict.PASS
        elif record.gate_outcome is GateOutcome.REJECTED:
            subject = subject_for_issue(record.issue_number)
            verdict = Verdict.FAIL
        else:
            continue
        verdicts.append(
            JudgeVerdictRecord(
                judge_id=JUDGE_ID,
                judge_family=JUDGE_FAMILY,
                subject_id=subject,
                verdict=verdict,
                confidence=BINARY_VERDICT_CONFIDENCE,
                recorded_at=record.recorded_at,
            )
        )
    return verdicts


def resolved_escapes(
    outcomes: Sequence[IssueOutcome],
    *,
    now: datetime,
    grace_window: timedelta = DEFAULT_GRACE_WINDOW,
) -> dict[int, bool]:
    """Issue → escaped, for the outcomes that are actually resolved *yet*.

    The single place the grace window is applied, so every rate in the report
    obeys one rule (ADR-0127 Ruling 4, whose ``resolve_outcomes`` this mirrors
    for a PR-keyed rather than verdict-keyed subject):

    * an attributed escape resolves **bad immediately** — an escape is definitive
      and waiting cannot un-observe it;
    * a clean reading resolves **good only once ``closed_at`` has cleared
      ``grace_window``** — escapes surface with a lag, so a fresh merge has had no
      chance to accumulate one and calling it clean would credit the gate for
      work nothing has checked;
    * a clean reading with **no ``closed_at``** stays unresolved — "we cannot
      date it" is the same epistemic state as "too recent", never "old enough";
    * no ledger consulted (``escaped is None``) or no closing PR → unresolved.

    Unresolved issues are simply absent from the mapping and counted in
    :class:`Identifiability`, never defaulted either way.
    """
    resolved: dict[int, bool] = {}
    for outcome in outcomes:
        if outcome.escaped is None or not outcome.closing_prs:
            continue
        if outcome.escaped:
            resolved[outcome.issue_number] = True
            continue
        if outcome.closed_at is None or now - outcome.closed_at <= grace_window:
            continue
        resolved[outcome.issue_number] = False
    return resolved


def _escape_outcomes(
    outcomes: Sequence[IssueOutcome], resolved: Mapping[int, bool]
) -> list[Outcome]:
    """Resolved issue outcomes → ``judge_calibration`` PR-keyed outcomes."""
    return [
        Outcome(
            subject_for_pr(outcome.closing_prs[0]),
            good=not resolved[outcome.issue_number],
        )
        for outcome in outcomes
        if outcome.issue_number in resolved and outcome.closing_prs
    ]


# --- the report -----------------------------------------------------------------


def _summarise_source(
    verdict_source: str,
    rejections: Sequence[AdequacyRunRecord],
    last_acceptance: Mapping[int, datetime],
    resolved_escape: Mapping[int, bool],
    suspects_by_issue: Mapping[int, int],
) -> VerdictSourceSummary:
    """Build one verdict source's row of the report.

    ``recovery`` counts issues whose *last* acceptance in the corpus came after
    their *first* rejection by this source — the issue eventually satisfied the
    gate rather than burning its attempts. ``resolved_escape`` is already
    grace-windowed by :func:`resolved_escapes`; issues absent from it contribute
    to no denominator.
    """
    issues = sorted({r.issue_number for r in rejections})
    first_rejection = {
        issue: min(r.recorded_at for r in rejections if r.issue_number == issue)
        for issue in issues
    }
    recovered = sum(
        1
        for issue in issues
        if issue in last_acceptance and last_acceptance[issue] > first_rejection[issue]
    )
    escaped_pairs = [
        resolved_escape[issue] for issue in issues if issue in resolved_escape
    ]
    grades = Counter(grade_finding(f) for r in rejections for f in r.findings)
    n_findings = sum(grades.values())
    costs = [r.duration_seconds / 60.0 for r in rejections if r.duration_seconds > 0]
    return VerdictSourceSummary(
        verdict_source=verdict_source,
        n_rejections=len(rejections),
        n_issues=len(issues),
        recovery=wilson_interval(recovered, len(issues)),
        post_rework_escape=wilson_interval(
            sum(1 for e in escaped_pairs if e), len(escaped_pairs)
        ),
        demonstrated_share=wilson_interval(
            grades.get(EvidenceGrade.DEMONSTRATED, 0), n_findings
        ),
        evidence_mix=dict(grades),
        n_suspect=sum(suspects_by_issue.get(issue, 0) for issue in issues),
        median_cost_minutes=statistics.median(costs) if costs else None,
    )


def _assess_identifiability(
    n_rejections: int,
    n_rejections_resolved: int,
    n_acceptances: int,
    n_acceptances_resolved: int,
    n_grace_censored: int = 0,
) -> Identifiability:
    """State plainly what this corpus can and cannot establish."""
    reasons: list[str] = []
    if n_rejections and n_rejections_resolved == 0:
        reasons.append(
            "reject arm is outcome-censored: rejected work never merges, and the "
            "escape ledger keys defects to an originating PR, so no rejection can "
            "ever resolve to a good/bad outcome"
        )
    if n_grace_censored:
        reasons.append(
            f"{n_grace_censored} issue(s) read escape-free but are held unresolved "
            "— their closing work is inside the escape-detection grace window, or "
            "carries no close date to age it against"
        )
    if n_acceptances_resolved == 0:
        reasons.append(
            "accept arm has no resolvable outcome (no closing PR joined to the "
            "escape ledger), so the gate's miss rate is unmeasured"
        )
    elif n_acceptances_resolved < 10:
        reasons.append(
            f"accept arm resolves only {n_acceptances_resolved} outcomes — below "
            "the judge-calibration confidence floor, so the proper score is "
            "indicative, not established"
        )
    if not n_rejections and not n_acceptances:
        reasons.append("empty corpus: no gate decision to score")
    return Identifiability(
        n_rejections=n_rejections,
        n_rejections_resolved=n_rejections_resolved,
        n_acceptances=n_acceptances,
        n_acceptances_resolved=n_acceptances_resolved,
        under_determined=bool(reasons),
        reasons=tuple(reasons),
    )


def calibrate(
    records: Sequence[AdequacyRunRecord],
    outcomes: Sequence[IssueOutcome],
    *,
    now: datetime,
    grace_window: timedelta = DEFAULT_GRACE_WINDOW,
) -> CalibrationReport:
    """Score the test-adequacy gate over a run corpus — the instrument entrypoint.

    Pure: ``records`` come from the loader, ``outcomes`` from the injected
    ground-truth seam, ``now`` from the caller. Every rate is reported with a
    Wilson interval and every degenerate case yields ``None`` rather than a
    fabricated number.

    ``now`` + ``grace_window`` are load-bearing, not decoration: they are what
    :func:`resolved_escapes` uses to hold a too-recent clean reading unresolved
    instead of scoring it good (ADR-0127's escape-detection lag).

    Read :attr:`CalibrationReport.identifiability` first. While
    ``under_determined`` is set, the point estimates describe the corpus but do
    NOT license a change to the gate's strictness.
    """
    rejections = [r for r in records if r.gate_outcome is GateOutcome.REJECTED]
    acceptances = [r for r in records if r.gate_outcome is GateOutcome.ACCEPTED]
    not_reached = [r for r in records if r.gate_outcome is GateOutcome.NOT_REACHED]

    last_acceptance: dict[int, datetime] = {}
    for record in acceptances:
        prior = last_acceptance.get(record.issue_number)
        if prior is None or record.recorded_at > prior:
            last_acceptance[record.issue_number] = record.recorded_at
    resolved_escape = resolved_escapes(outcomes, now=now, grace_window=grace_window)
    grace_censored = sum(
        1
        for o in outcomes
        if o.escaped is False
        and o.closing_prs
        and o.issue_number not in resolved_escape
    )
    suspects = suspect_rejections(records)
    suspects_by_issue = Counter(s.issue_number for s in suspects)

    by_source: dict[str, list[AdequacyRunRecord]] = defaultdict(list)
    for record in rejections:
        by_source[record.verdict_source or VERDICT_SOURCE_LLM_FAIL].append(record)
    summaries = tuple(
        _summarise_source(
            source,
            by_source[source],
            last_acceptance,
            resolved_escape,
            suspects_by_issue,
        )
        for source in VERDICT_SOURCES
        if by_source.get(source)
    )

    # The two arms are resolved separately so the reject arm's zero is a
    # measured result, not an artefact of a shared filter (see module docstring).
    escape_outcomes = _escape_outcomes(outcomes, resolved_escape)
    accept_arm = resolve(to_judge_verdicts(acceptances, outcomes), escape_outcomes)
    reject_arm = resolve(to_judge_verdicts(rejections, outcomes), escape_outcomes)
    score = score_judge(JUDGE_ID, JUDGE_FAMILY, accept_arm)

    costs = [r.duration_seconds / 60.0 for r in rejections if r.duration_seconds > 0]
    stamps = [r.recorded_at for r in records]
    return CalibrationReport(
        window_start=min(stamps) if stamps else None,
        window_end=max(stamps) if stamps else None,
        n_runs=len(records),
        n_accepted=len(acceptances),
        n_rejected=len(rejections),
        n_not_reached=len(not_reached),
        n_structured=sum(1 for r in records if r.shape is RecordShape.STRUCTURED),
        median_rejection_minutes=statistics.median(costs) if costs else None,
        rejection_hours=sum(r.duration_seconds for r in rejections) / 3600.0,
        by_verdict_source=summaries,
        stationarity=demand_stationarity(records),
        anchoring=demand_anchoring(records),
        pinned_demand=pinned_demand_overlap(records),
        accept_arm_score=score,
        identifiability=_assess_identifiability(
            n_rejections=len(rejections),
            n_rejections_resolved=len(reject_arm),
            n_acceptances=len(acceptances),
            n_acceptances_resolved=len(accept_arm),
            n_grace_censored=grace_censored,
        ),
        suspect_rejections=suspects,
    )
