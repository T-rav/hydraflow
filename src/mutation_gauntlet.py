"""Mutation Gauntlet — gate-sensitivity instrument (pure core). #10835.

The factory publishes a claim it cannot currently check: **the gates are
real.** A green gauntlet is consistent with both "the change was good" and
"the gate is insensitive," and nothing distinguishes those. The *escape
ledger* (``escape.ledger``, #10367) measures this retrospectively — defects
that already got through. This module is the **prospective twin**: inject a
known fault, run the gate that owns it, and observe whether the gate goes red.

This file is the PURE CORE — no subprocess, no git, no I/O — so the
verdict/kill-rate logic is fully unit-testable. The thin I/O shell
(``scripts/mutation_gauntlet.py``) materializes scratch worktrees, applies the
patch, runs the real gate, and calls back into ``classify_result`` /
``summarize`` here.

Verdict semantics (honest, fail-closed):

* ``KILLED``   — the gate ran and went red (nonzero exit). The fault was caught.
* ``SURVIVED`` — the gate ran and stayed green (exit 0) despite the injected
  fault. This is a **finding**: the gate is blind to a fault it owns.
* ``ERRORED``  — the gate could not run cleanly (worktree/patch failure, gate
  crash). NEVER silently counted as killed; excluded from the kill-rate
  denominator but always counted and reported.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MutantClass(StrEnum):
    """The fault family a mutant injects — each localizes ONE owning gate."""

    LOGIC = "logic"
    CONTRACT = "contract"
    SCENARIO = "scenario"
    VOCABULARY = "vocabulary"
    ADR = "adr"
    SAFETY = "safety"


class Verdict(StrEnum):
    """Outcome of running a mutant through its owning gate."""

    KILLED = "killed"
    SURVIVED = "survived"
    ERRORED = "errored"


@dataclass(frozen=True)
class PatchSpec:
    """A ``(file, find, replace)`` mutation applied to a scratch worktree.

    ``find`` must be a substring present in ``file`` at HEAD; the shell applies
    a single, first-occurrence string replacement so the mutation point stays
    surgical and unambiguous.
    """

    file: str
    find: str
    replace: str

    @property
    def is_well_formed(self) -> bool:
        """A patch is well-formed when it names a file, has a non-empty
        ``find`` anchor, and actually changes something (``find != replace``).
        """
        return bool(self.file) and bool(self.find) and self.find != self.replace


@dataclass(frozen=True)
class Mutant:
    """One curated, version-controlled fault + the gate that MUST kill it."""

    id: str
    mutant_class: MutantClass
    target_gate: str
    patch: PatchSpec
    rationale: str
    expectation: Verdict = Verdict.KILLED


@dataclass(frozen=True)
class MutantResult:
    """The outcome of running one mutant through its ``target_gate``.

    ``gate_exit`` is ``None`` when the gate never ran (an ``ERRORED`` result
    where the failure was upstream of the gate, e.g. the patch did not apply).
    """

    mutant: Mutant
    verdict: Verdict
    gate_exit: int | None
    detail: str = ""


@dataclass(frozen=True)
class MutantSelector:
    """Optional filter over a catalog. ``None`` fields impose no constraint."""

    ids: frozenset[str] | None = None
    classes: frozenset[MutantClass] | None = None
    gates: frozenset[str] | None = None

    def matches(self, mutant: Mutant) -> bool:
        """Return whether *mutant* passes every declared filter."""
        if self.ids is not None and mutant.id not in self.ids:
            return False
        if self.classes is not None and mutant.mutant_class not in self.classes:
            return False
        return not (self.gates is not None and mutant.target_gate not in self.gates)


@dataclass(frozen=True)
class GateKillStats:
    """Killed / survived / errored tallies for one bucket (a gate or a class)."""

    killed: int = 0
    survived: int = 0
    errored: int = 0

    @property
    def scored(self) -> int:
        """Mutants that produced a real verdict — the kill-rate denominator.

        ``ERRORED`` mutants are deliberately excluded: a gate that could not
        run tells us nothing about its sensitivity.
        """
        return self.killed + self.survived

    @property
    def kill_rate(self) -> float | None:
        """``killed / (killed + survived)``, or ``None`` when nothing scored.

        ``None`` (rather than ``0.0``) is the honest reading of an empty or
        all-errored bucket: no evidence, not "0% caught". Callers render it as
        ``n/a``.
        """
        if self.scored == 0:
            return None
        return self.killed / self.scored


@dataclass(frozen=True)
class KillRateReport:
    """Per-gate + per-class kill rates plus the actionable findings."""

    overall: GateKillStats
    per_gate: dict[str, GateKillStats]
    per_class: dict[MutantClass, GateKillStats]
    survivors: tuple[Mutant, ...]
    errored: tuple[Mutant, ...]

    @property
    def has_survivors(self) -> bool:
        """True when at least one gate was blind to a fault it owns."""
        return bool(self.survivors)

    @property
    def has_errors(self) -> bool:
        """True when at least one mutant could not be scored."""
        return bool(self.errored)


def plan_campaign(
    catalog: Sequence[Mutant], selector: MutantSelector | None = None
) -> list[Mutant]:
    """Return the mutants from *catalog* that pass *selector* (all if ``None``)."""
    if selector is None:
        return list(catalog)
    return [mutant for mutant in catalog if selector.matches(mutant)]


def classify_result(gate_exit_code: int, gate_ran: bool) -> Verdict:
    """Map a gate run to a verdict — pure and fail-closed.

    * gate could not run (``gate_ran`` is False) -> ``ERRORED``
    * gate ran and went red (nonzero exit)       -> ``KILLED``
    * gate ran and stayed green (exit 0)         -> ``SURVIVED``
    """
    if not gate_ran:
        return Verdict.ERRORED
    if gate_exit_code != 0:
        return Verdict.KILLED
    return Verdict.SURVIVED


def _tally(results: Sequence[MutantResult]) -> GateKillStats:
    """Count verdicts across *results* into a :class:`GateKillStats`."""
    killed = sum(1 for r in results if r.verdict is Verdict.KILLED)
    survived = sum(1 for r in results if r.verdict is Verdict.SURVIVED)
    errored = sum(1 for r in results if r.verdict is Verdict.ERRORED)
    return GateKillStats(killed=killed, survived=survived, errored=errored)


def summarize(results: Sequence[MutantResult]) -> KillRateReport:
    """Aggregate *results* into a per-gate + per-class kill-rate report.

    Handles the empty campaign without dividing by zero (every ``kill_rate``
    reads ``None``). ``ERRORED`` rows are counted and reported but never enter
    a kill-rate denominator, and a ``SURVIVED`` row is surfaced as a finding.
    """
    by_gate: dict[str, list[MutantResult]] = defaultdict(list)
    by_class: dict[MutantClass, list[MutantResult]] = defaultdict(list)
    for result in results:
        by_gate[result.mutant.target_gate].append(result)
        by_class[result.mutant.mutant_class].append(result)
    return KillRateReport(
        overall=_tally(results),
        per_gate={gate: _tally(rs) for gate, rs in by_gate.items()},
        per_class={cls: _tally(rs) for cls, rs in by_class.items()},
        survivors=tuple(r.mutant for r in results if r.verdict is Verdict.SURVIVED),
        errored=tuple(r.mutant for r in results if r.verdict is Verdict.ERRORED),
    )


def _stats_dict(stats: GateKillStats) -> dict[str, Any]:
    """Serialize one :class:`GateKillStats` to a JSON-safe dict."""
    return {
        "killed": stats.killed,
        "survived": stats.survived,
        "errored": stats.errored,
        "kill_rate": stats.kill_rate,
    }


def campaign_row(
    report: KillRateReport, *, campaign_id: str, head_sha: str, ts: str
) -> dict[str, Any]:
    """Build the append-only ``gate_kill_rate.jsonl`` row for one campaign.

    Kept in the pure core so the row schema is unit-testable; the shell
    supplies ``ts`` / ``head_sha`` / ``campaign_id`` from the live environment.
    """
    return {
        "campaign_id": campaign_id,
        "ts": ts,
        "head_sha": head_sha,
        "overall": _stats_dict(report.overall),
        "per_gate": {
            gate: _stats_dict(stats) for gate, stats in sorted(report.per_gate.items())
        },
        "per_class": {
            cls.value: _stats_dict(stats)
            for cls, stats in sorted(
                report.per_class.items(), key=lambda kv: kv[0].value
            )
        },
        "survivors": [mutant.id for mutant in report.survivors],
        "errored": [mutant.id for mutant in report.errored],
    }


def _fmt_rate(stats: GateKillStats) -> str:
    """Render a kill rate as a percentage, or ``n/a`` when nothing scored."""
    return "n/a" if stats.kill_rate is None else f"{stats.kill_rate:.0%}"


def render_summary(report: KillRateReport) -> str:
    """Render a human-readable stdout summary of a campaign."""
    ov = report.overall
    lines = [
        f"Mutation gauntlet — overall kill rate: {_fmt_rate(ov)} "
        f"({ov.killed} killed / {ov.survived} survived / {ov.errored} errored)",
        "",
        "Per gate:",
    ]
    for gate, stats in sorted(report.per_gate.items()):
        lines.append(
            f"  {gate}: {_fmt_rate(stats)} "
            f"({stats.killed}K/{stats.survived}S/{stats.errored}E)"
        )
    lines.append("Per class:")
    for cls, stats in sorted(report.per_class.items(), key=lambda kv: kv[0].value):
        lines.append(
            f"  {cls.value}: {_fmt_rate(stats)} "
            f"({stats.killed}K/{stats.survived}S/{stats.errored}E)"
        )
    if report.survivors:
        lines.append("")
        lines.append("SURVIVORS (blind gates — findings, not runner failures):")
        for mutant in report.survivors:
            lines.append(
                f"  ! {mutant.id} [{mutant.mutant_class.value}] "
                f"target_gate={mutant.target_gate}"
            )
    if report.errored:
        lines.append("")
        lines.append("ERRORED (could not run — NOT counted as killed):")
        for mutant in report.errored:
            lines.append(f"  ? {mutant.id} [{mutant.mutant_class.value}]")
    return "\n".join(lines)
