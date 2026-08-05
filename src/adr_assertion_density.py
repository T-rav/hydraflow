"""Checkable-assertion density per ADR series (#10917, epic #10914).

The second setpoint-erosion series. Frontmatter *presence* of ``**Enforced by:**``
is saturated (44/45 Accepted ADRs declare enforcement) and cannot move, so it is
useless as an erosion setpoint. The actionable axis is the **density and kind of
checks**: an ADR whose enforcement is ``pytest:tests/test_x.py`` carries a higher
*checkable-assertion density* than one enforced only by ``prose``. A decline in
that density across the Accepted corpus — especially if concentrated in a subset
of ADRs — is an erosion signal orthogonal to the REAL/WEAK/MISSING enforcement
*quality* classification (``adr_conformance.classify_adr_enforcement``): this
series counts *how executable* the cited enforcement is, not *how real* a given
check turns out to be when resolved against the tree.

Pure engine — no I/O, no resolution against disk. It reads only the already-parsed
``ADR.enforced_by`` typed checks (``adr_index.Check``, kind ∈ pytest|make|script|
prose). ``pytest``/``make``/``script`` are *executable* assertions; ``prose`` is
not. Density is the executable share of an ADR's cited checks.

Deferred (honest limitation): a true **monthly time-series** and the shared
Shewhart *baseline framework* live in the epic's framework child (#10915,
human-required). This module ships the per-ADR + population snapshot and reuses
the existing ``judge_independence.shewhart_c_chart_ucl`` for an indicative
control limit on the per-ADR prose-check count; the longitudinal trend is a
later phase.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from adr_index import ADR, Check
from judge_independence import shewhart_c_chart_ucl

#: Check kinds whose cited enforcement is machine-executable (an *assertion*),
#: as opposed to ``prose`` (a soft, human-resolved binding).
EXECUTABLE_KINDS: frozenset[str] = frozenset({"pytest", "make", "script"})

#: Stable ordering for the kind-count breakdown (executable first, prose last).
CHECK_KINDS: tuple[str, ...] = ("pytest", "make", "script", "prose")

#: The population this series tracks by default. Superseded/Deprecated ADRs are
#: frozen history; Proposed ones are not yet load-bearing — only Accepted ADRs
#: are the live governed corpus whose enforcement density should not erode.
DEFAULT_POPULATION: tuple[str, ...] = ("Accepted",)


def check_is_executable(check: Check) -> bool:
    """True when a cited check is a machine-executable assertion (not prose)."""
    return check.kind in EXECUTABLE_KINDS


@dataclass(frozen=True)
class AdrDensity:
    """One ADR's checkable-assertion density.

    ``density`` is the executable share of the ADR's cited checks —
    ``executable_checks / total_checks`` — in ``[0.0, 1.0]``, or ``0.0`` when the
    ADR cites no checks at all (an unenforced decision reads as zero density, not
    an undefined one).
    """

    number: int
    title: str
    status: str
    total_checks: int
    executable_checks: int
    prose_checks: int
    kind_counts: dict[str, int]
    density: float

    def to_json_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "title": self.title,
            "status": self.status,
            "total_checks": self.total_checks,
            "executable_checks": self.executable_checks,
            "prose_checks": self.prose_checks,
            "kind_counts": dict(self.kind_counts),
            "density": self.density,
        }


def density_for_adr(adr: ADR) -> AdrDensity:
    """Compute one ADR's checkable-assertion density from its parsed checks."""
    counts = Counter(check.kind for check in adr.enforced_by)
    kind_counts = {kind: counts.get(kind, 0) for kind in CHECK_KINDS}
    total = sum(kind_counts.values())
    executable = sum(kind_counts[kind] for kind in EXECUTABLE_KINDS)
    prose = kind_counts["prose"]
    density = executable / total if total else 0.0
    return AdrDensity(
        number=adr.number,
        title=adr.title,
        status=adr.status,
        total_checks=total,
        executable_checks=executable,
        prose_checks=prose,
        kind_counts=kind_counts,
        density=density,
    )


@dataclass(frozen=True)
class PopulationDensity:
    """Checkable-assertion density aggregated across a status population.

    ``mean_density`` is the unweighted mean of per-ADR density (each ADR counts
    once, so a verbose ADR does not dominate); ``executable_fraction`` is the
    check-weighted share (executable checks / all checks). Reporting both keeps a
    corpus that adds one all-prose ADR distinguishable from one that dilutes an
    executable ADR.

    ``prose_ucl`` is a Shewhart c-chart upper control limit on the per-ADR prose
    count; ``prose_outliers`` are the ADRs above it — where non-executable
    enforcement is anomalously concentrated, the erosion signal to look at first.
    """

    statuses: tuple[str, ...]
    n_adrs: int
    per_adr: tuple[AdrDensity, ...]
    total_checks: int
    total_executable: int
    total_prose: int
    kind_totals: dict[str, int]
    mean_density: float
    executable_fraction: float
    prose_ucl: float
    prose_outliers: tuple[int, ...]


def population_density(
    adrs: Iterable[ADR], *, statuses: Sequence[str] = DEFAULT_POPULATION
) -> PopulationDensity:
    """Aggregate checkable-assertion density across ADRs in ``statuses``."""
    wanted = tuple(statuses)
    selected = sorted(
        (density_for_adr(adr) for adr in adrs if adr.status in wanted),
        key=lambda d: d.number,
    )
    n = len(selected)
    total_checks = sum(d.total_checks for d in selected)
    total_executable = sum(d.executable_checks for d in selected)
    total_prose = sum(d.prose_checks for d in selected)
    kind_totals = {
        kind: sum(d.kind_counts[kind] for d in selected) for kind in CHECK_KINDS
    }
    mean_density = sum(d.density for d in selected) / n if n else 0.0
    executable_fraction = total_executable / total_checks if total_checks else 0.0
    prose_ucl = shewhart_c_chart_ucl([float(d.prose_checks) for d in selected])
    prose_outliers = tuple(d.number for d in selected if d.prose_checks > prose_ucl)
    return PopulationDensity(
        statuses=wanted,
        n_adrs=n,
        per_adr=tuple(selected),
        total_checks=total_checks,
        total_executable=total_executable,
        total_prose=total_prose,
        kind_totals=kind_totals,
        mean_density=mean_density,
        executable_fraction=executable_fraction,
        prose_ucl=prose_ucl,
        prose_outliers=prose_outliers,
    )
