"""Mode-mismatch ledger — was the fixed pipeline the right DAG? (#11055, rung 0).

Rung 0 of the five-modes self-adaptive roadmap (epic #11035, roadmap-of-record
comment 2026-08-12). Before the factory grows a mode router, measure whether it
needs one: for every issue that reached a terminal state, retro-classify from
the *existing exhaust* what flow the issue actually needed — the fixed
``find → plan → ready → review → fixed`` build DAG, or one of the flows the
roadmap would add (probe / clarify / collaborate / oracle / earlier-decompose).
The headline number, the **wrong-DAG rate**, is the go/no-go gate for every
later rung; the decision rule is rendered into the report so the number decides,
not vibes.

Deliberately deterministic: every rule is a threshold over recorded signals.
A generative classifier here would itself need finder-calibration (ADR-0126)
before its output counted — do not bootstrap the instrument on an uncalibrated
sensor.

Pure engine over :class:`IssueTrace` values; assembling traces from
``events.jsonl`` + issue states is the runner's job
(``scripts/mode_mismatch_report.py``, quiet-week pattern — on demand, not a
loop).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: Route-backs at or above this count on a MERGED issue read as "the issue
#: needed an iterate-with-review flow, not one-shot delegation". Below it,
#: ordinary retry noise. Coarse by design — rung 0 needs a base rate, not a
#: per-issue adjudication.
DEFAULT_CHURN_THRESHOLD = 3

#: Below this many terminal issues the wrong-DAG rate is directional only —
#: a proportion on a handful of issues cannot gate a 12-month roadmap.
MIN_DECISIVE_SAMPLE = 30

#: Decision-rule boundaries (fractions). Written into the report verbatim so
#: the gate is legible: below the floor the fixed DAG is vindicated; above the
#: ceiling rung 1 proceeds; between them, keep measuring.
VINDICATED_BELOW = 0.10
PROCEED_AT = 0.15


class Mode(StrEnum):
    """What the issue retrospectively *needed* (BUILD = the fixed DAG was right)."""

    BUILD = "build"
    PROBE = "probe"
    CLARIFY = "clarify"
    COLLABORATE = "collaborate"
    ORACLE = "oracle"
    DECOMPOSE_EARLIER = "decompose_earlier"


@dataclass(frozen=True, slots=True)
class IssueTrace:
    """One issue's recorded journey, assembled from existing exhaust.

    ``merged`` — a PR for this issue merged. ``closed_unmerged`` — the issue
    reached a closed state with no merge (the ``state_reason`` — not_planned,
    duplicate — arrives via the issue-states input). ``work_started`` — the
    pipeline spent at least one implement attempt on it (an issue closed
    before any work is triage noise, not a mode mismatch). ``route_backs`` —
    stage regressions recorded for the issue. ``hitl_escalations`` — HITL
    surfaces raised while working it. ``gave_up`` — the give-up window fired /
    attempts exhausted without convergence. ``decomposed_after_attempt`` — the
    issue was split into children only after a failed monolithic attempt.
    """

    issue_number: int
    merged: bool = False
    closed_unmerged: bool = False
    work_started: bool = False
    route_backs: int = 0
    hitl_escalations: int = 0
    gave_up: bool = False
    decomposed_after_attempt: bool = False

    @property
    def terminal(self) -> bool:
        """Whether the issue's journey ended (merged, closed, or given up)."""
        return self.merged or self.closed_unmerged or self.gave_up


@dataclass(frozen=True, slots=True)
class ModeMismatchVerdict:
    """The retro-verdict for one terminal issue: what flow it needed, and why."""

    issue_number: int
    needed: Mode
    signals: tuple[str, ...]

    @property
    def wrong_dag(self) -> bool:
        """True when the fixed build DAG was the wrong flow for this issue."""
        return self.needed is not Mode.BUILD


def classify(
    trace: IssueTrace, *, churn_threshold: int = DEFAULT_CHURN_THRESHOLD
) -> ModeMismatchVerdict | None:
    """Retro-classify one issue; ``None`` for non-terminal or never-worked issues.

    Rule order IS precedence (first match wins), strongest signal first:

    1. gave up → **probe**: attempts exhausted without convergence means the
       frame, not the effort, was wrong — a bounded experiment (or the clarify
       it would have triggered) should have preceded a full build.
    2. closed unmerged after work started → **oracle**: the factory built at a
       question (invalid / duplicate / wontfix discovered mid-work).
    3. decomposed only after a failed attempt → **decompose_earlier**: intake
       misclassified size.
    4. merged, but HITL had to interpret → **clarify**: the distinguishing
       question existed and was asked late, by escalation instead of intake.
    5. merged with heavy route-back churn → **collaborate**: it converged, but
       as an iterate-with-review flow in all but name.
    6. merged clean → **build**: the fixed DAG was the right machine (the
       denominator's honest majority, if the pipeline is well matched).
    """
    if not trace.terminal or not trace.work_started:
        return None
    # Rule order IS precedence — the tuple is the table the docstring describes.
    rules: tuple[tuple[bool, Mode, str], ...] = (
        (trace.gave_up, Mode.PROBE, "give-up window fired"),
        (
            trace.closed_unmerged,
            Mode.ORACLE,
            "closed without merge after work started",
        ),
        (
            trace.decomposed_after_attempt,
            Mode.DECOMPOSE_EARLIER,
            "decomposed only after a failed monolithic attempt",
        ),
        (
            trace.hitl_escalations > 0,
            Mode.CLARIFY,
            f"{trace.hitl_escalations} HITL escalation(s) before merge",
        ),
        (
            trace.route_backs >= churn_threshold,
            Mode.COLLABORATE,
            f"{trace.route_backs} route-backs (churn threshold {churn_threshold})",
        ),
    )
    for hit, mode, signal in rules:
        if hit:
            return ModeMismatchVerdict(trace.issue_number, mode, (signal,))
    return ModeMismatchVerdict(trace.issue_number, Mode.BUILD, ())


@dataclass(frozen=True, slots=True)
class MismatchReport:
    """The aggregate: the wrong-DAG rate and its decomposition."""

    total: int
    wrong: int
    by_mode: dict[Mode, int]

    @property
    def rate(self) -> float:
        """Wrong-DAG fraction; 0.0 on an empty population (no evidence ≠ vindication)."""
        return self.wrong / self.total if self.total else 0.0


def summarize(verdicts: Iterable[ModeMismatchVerdict]) -> MismatchReport:
    """Fold per-issue verdicts into the report."""
    counts: Counter[Mode] = Counter()
    for verdict in verdicts:
        counts[verdict.needed] += 1
    total = sum(counts.values())
    wrong = total - counts.get(Mode.BUILD, 0)
    return MismatchReport(total=total, wrong=wrong, by_mode=dict(counts))


def discriminating(traces: Sequence[IssueTrace]) -> bool:
    """Could this population have produced a NON-build verdict at all?

    Every non-build rule keys off a signal that may simply be absent from
    the exhaust (no HITL events emitted, route-backs not yet captured,
    give-up not recorded). When NO trace carries ANY discriminating
    signal, a 0% wrong-DAG rate measures the instrument, not the factory —
    and "FIXED DAG VINDICATED" would close a 12-month roadmap on a
    tautology. This is the anti-vacuity gate: rate is only meaningful when
    a non-build verdict was reachable.
    """
    return any(
        trace.gave_up
        or trace.closed_unmerged
        or trace.decomposed_after_attempt
        or trace.hitl_escalations > 0
        or trace.route_backs > 0
        # Only the CLASSIFIED population counts: a signal on a trace that
        # never reaches classify() (not terminal, or never worked) cannot
        # produce a non-build verdict, so counting it would re-open the
        # tautology this gate exists to close.
        for trace in traces
        if trace.terminal and trace.work_started
    )


def decision(report: MismatchReport, *, discriminating_signals: bool = True) -> str:
    """The go/no-go sentence the roadmap gates on — rendered, never implied.

    *discriminating_signals* comes from :func:`discriminating`. False means
    the classifier could only ever have said "build", so no verdict about
    the FACTORY can be drawn — only about the instrument.
    """
    if not discriminating_signals:
        return (
            "INSTRUMENT NOT DISCRIMINATING — no terminal issue carried any "
            "non-build signal (HITL escalations, route-backs, give-up, "
            "closed-unmerged, late decomposition), so a 0% wrong-DAG rate "
            "measures the EXHAUST, not the pipeline. Neither vindication nor "
            "proceed may be read from this run: capture the missing signals "
            "(flow-of-record, #11027 family) and re-run."
        )
    if report.total < MIN_DECISIVE_SAMPLE:
        return (
            f"INSUFFICIENT EVIDENCE — {report.total} terminal issues "
            f"(< {MIN_DECISIVE_SAMPLE}); the rate is directional only. Keep "
            "measuring; no rung proceeds or closes on this sample."
        )
    if report.rate < VINDICATED_BELOW:
        return (
            f"FIXED DAG VINDICATED — wrong-DAG rate {report.rate:.0%} < "
            f"{VINDICATED_BELOW:.0%}. The five-modes direction closes with "
            "evidence; epic #11035 records the number."
        )
    if report.rate >= PROCEED_AT:
        return (
            f"PROCEED TO RUNG 1 — wrong-DAG rate {report.rate:.0%} ≥ "
            f"{PROCEED_AT:.0%}. The give-up third outlet (transition to "
            "clarify/probe instead of parking) is justified by this base rate."
        )
    return (
        f"BORDERLINE — wrong-DAG rate {report.rate:.0%} sits between "
        f"{VINDICATED_BELOW:.0%} and {PROCEED_AT:.0%}. Keep measuring; "
        "re-run after more terminal issues accumulate."
    )


def render_report(
    report: MismatchReport, *, discriminating_signals: bool = True
) -> str:
    """Markdown report: headline rate, decomposition, decision rule, honesty notes."""
    out = "# Mode-Mismatch Report (five-modes rung 0, #11055)\n\n"
    out += (
        "Retro-classification of terminal issues from existing exhaust: what "
        "flow did each issue actually need? **BUILD means the fixed pipeline "
        "was right.** Deterministic rules only — thresholds over recorded "
        "signals, no generative classifier.\n\n"
    )
    out += "## Headline\n\n"
    out += f"- **Terminal issues classified:** {report.total}\n"
    out += f"- **Wrong-DAG count:** {report.wrong}\n"
    out += f"- **Wrong-DAG rate:** {report.rate:.1%}\n\n"
    out += (
        "**Decision:** "
        f"{decision(report, discriminating_signals=discriminating_signals)}\n\n"
    )
    out += "## Decomposition\n\n| Needed | Issues |\n|---|---:|\n"
    for mode in Mode:
        if mode in report.by_mode:
            out += f"| {mode.value} | {report.by_mode[mode]} |\n"
    out += (
        "\n> Honesty notes: the CLARIFY rule counts *any* pre-merge HITL "
        "escalation (interpretation vs permission is not yet distinguishable "
        "in the exhaust — flow-of-record capture, designed with #11027, "
        "sharpens this). Rates on fewer than "
        f"{MIN_DECISIVE_SAMPLE} issues are directional only.\n"
    )
    return out


def verdict_row(verdict: ModeMismatchVerdict) -> dict[str, object]:
    """One append-only ledger row (stable keys; the ledger is the record)."""
    return {
        "issue": verdict.issue_number,
        "needed": verdict.needed.value,
        "wrong_dag": verdict.wrong_dag,
        "signals": list(verdict.signals),
    }


def write_ledger(path: Path, verdicts: Sequence[ModeMismatchVerdict]) -> int:
    """Append verdict rows as JSONL; returns rows written. Parent dirs created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for verdict in verdicts:
            fh.write(json.dumps(verdict_row(verdict), sort_keys=True) + "\n")
    return len(verdicts)
