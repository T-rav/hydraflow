"""Render the ADR *checkable-assertion density* series (#10917, epic #10914).

The second setpoint-erosion series. Frontmatter presence of ``**Enforced by:**``
is saturated and cannot move; the actionable axis is how *executable* the cited
enforcement is. This surface reports, across the Accepted corpus, the density of
executable (``pytest``/``make``/``script``) versus ``prose`` checks — a decline
is an erosion signal orthogonal to the REAL/WEAK/MISSING enforcement-quality
lens the sibling ``adr-enforcement.md`` report carries.

Pure/deterministic: it reads only the already-parsed ``ADR.enforced_by`` typed
checks (no resolution against the tree), so — unlike ``adr-enforcement.md`` — its
output is a function of the ADR frontmatter alone and never moves when a cited
test's *body* changes. The scoring lives in the ``adr_assertion_density`` engine;
this module only renders it.
"""

from __future__ import annotations

from collections.abc import Iterable

from adr_assertion_density import CHECK_KINDS, AdrDensity, population_density
from adr_index import ADR

_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def _adr_ref(density: AdrDensity) -> str:
    return f"ADR-{density.number:04d}"


def _density_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def render_adr_assertion_density(adrs: Iterable[ADR]) -> str:
    """Render the checkable-assertion density report for the Accepted corpus."""
    pop = population_density(adrs)
    statuses = " / ".join(pop.statuses)

    out = "# ADR Checkable-Assertion Density\n\n"
    out += (
        "The **executable share** of each Accepted ADR's cited enforcement "
        "(`pytest` / `make` / `script` are executable assertions; `prose` is "
        "not). Frontmatter *presence* of enforcement is saturated and cannot "
        "move — this series tracks *how executable* that enforcement is, the "
        "erosion axis orthogonal to the REAL/WEAK/MISSING quality lens in "
        "[`adr-enforcement.md`](adr-enforcement.md). Density = executable checks "
        "/ all cited checks.\n\n"
    )

    if pop.n_adrs == 0:
        out += f"_(no ADRs in the {statuses} population)_"
        return out + _FOOTER

    # Headline aggregate — two complementary measures, per the engine's contract.
    out += "## Population\n\n"
    out += f"- **Population:** {statuses} ({pop.n_adrs} ADRs)\n"
    out += (
        f"- **Mean density** (per-ADR, unweighted): {_density_pct(pop.mean_density)}\n"
    )
    out += (
        f"- **Executable fraction** (check-weighted): "
        f"{_density_pct(pop.executable_fraction)} "
        f"({pop.total_executable} of {pop.total_checks} cited checks)\n"
    )
    kinds = ", ".join(f"{kind} {pop.kind_totals[kind]}" for kind in CHECK_KINDS)
    out += f"- **Check kinds:** {kinds}\n"
    out += (
        f"- **Prose-count control limit** (Shewhart c-chart UCL): {pop.prose_ucl:.2f}\n"
    )
    if pop.prose_outliers:
        refs = ", ".join(f"ADR-{n:04d}" for n in pop.prose_outliers)
        out += (
            f"- **Prose outliers** (non-executable enforcement anomalously "
            f"concentrated — look here first): {refs}\n"
        )
    else:
        out += "- **Prose outliers:** _(none above the control limit)_\n"

    out += (
        "\n> The monthly time-series and the shared Shewhart baseline framework "
        "are deferred to the epic's framework child (#10915). This surface is "
        "the per-PR snapshot; the longitudinal trend is a later phase.\n"
    )

    # Per-ADR table, lowest density first (most erosion-relevant at the top).
    out += "\n## Per-ADR density\n\n"
    out += "| ADR | Title | Density | Executable | Prose |\n"
    out += "|-----|-------|--------:|-----------:|------:|\n"
    for density in sorted(pop.per_adr, key=lambda d: (d.density, d.number)):
        out += (
            f"| {_adr_ref(density)} | {density.title} | "
            f"{_density_pct(density.density)} | {density.executable_checks} | "
            f"{density.prose_checks} |\n"
        )

    return out + _FOOTER
