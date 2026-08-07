"""Render the ADR *falsifiability* baseline (#10830 wiring / #10821 calibration).

The spec-intake gate (#10830, `spec_intake_gate.falsifiability_report`) measures
claim density — the fraction of a document's statements that carry a checkable
marker — to catch prose that asserts nothing falsifiable (the mush a stress test
cannot catch). ADR-0131 named the missing prerequisite: a prose critic is a
generative sensor with no natural zero, so *what it flags on ADRs already
considered sound must be measured before its flags on new specs are trusted*
(#10821).

This surface is that golden baseline. It runs the (deterministic) falsifiability
metric over every **Accepted** ADR body and reports the claim-density
distribution of the sound corpus, plus any ADR below the mush floor. It is the
reference the gate calibrates against — and it takes the spec-intake metric from
a tested-but-dormant engine to a live, per-PR arch artifact.

Deterministic: it reads only the on-disk ADR text (no model, no runtime data),
so its output is a function of the ADR corpus alone.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from adr_index import ADR
from spec_intake_gate import MUSH_DENSITY_FLOOR, falsifiability_report

_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def _density_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def render_adr_falsifiability(adrs: Iterable[ADR], *, repo_root: Path) -> str:
    """Render the claim-density baseline over the Accepted ADR corpus."""
    adr_dir = repo_root / "docs" / "adr"
    rows: list[tuple[ADR, float, int, int]] = []
    for adr in adrs:
        if adr.status != "Accepted":
            continue
        matches = sorted(adr_dir.glob(f"{adr.number:04d}-*.md"))
        if not matches:
            continue
        report = falsifiability_report(matches[0].read_text(encoding="utf-8"))
        if report.total_statements == 0:
            continue
        rows.append(
            (adr, report.claim_density, report.checkable_count, report.total_statements)
        )

    out = "# ADR Falsifiability Baseline\n\n"
    out += (
        "The **claim density** of each Accepted ADR — the fraction of its "
        "statements carrying a checkable marker (a normative keyword, code span, "
        "path, number, or named symbol). This is the *golden baseline* the "
        "spec-intake gate (#10830) calibrates against (#10821, ADR-0131): a prose "
        "critic has no natural zero, so the mush it flags on new specs is only "
        "trustworthy relative to what sound ADRs already score. Deterministic — "
        "a function of the ADR text alone.\n\n"
    )

    if not rows:
        return out + "_(no Accepted ADRs with prose to measure)_" + _FOOTER

    n = len(rows)
    mean_density = sum(d for _, d, _, _ in rows) / n
    mushy = [adr for adr, d, _, _ in rows if d < MUSH_DENSITY_FLOOR]

    out += "## Baseline\n\n"
    out += f"- **Population:** Accepted ({n} ADRs)\n"
    out += f"- **Mean claim density:** {_density_pct(mean_density)}\n"
    out += f"- **Mush floor:** {_density_pct(MUSH_DENSITY_FLOOR)} (density below this reads as mush)\n"
    if mushy:
        refs = ", ".join(f"ADR-{a.number:04d}" for a in mushy)
        out += (
            f"- **Below the mush floor** (unusually low claim density for a sound "
            f"ADR — look here first): {refs}\n"
        )
    else:
        out += "- **Below the mush floor:** _(none — the sound corpus clears it)_\n"

    out += "\n## Per-ADR claim density\n\n"
    out += "| ADR | Density | Checkable | Statements |\n"
    out += "|-----|--------:|----------:|-----------:|\n"
    for adr, density, checkable, total in sorted(
        rows, key=lambda r: (r[1], r[0].number)
    ):
        out += (
            f"| ADR-{adr.number:04d} | {_density_pct(density)} | "
            f"{checkable} | {total} |\n"
        )

    return out + _FOOTER
