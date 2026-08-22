"""Symbol-granularity authoring nudges for ADR citations (ADR-0136 §3).

Given an ADR index, flags every *bare* (`src/foo.py`, no `:Symbol` tail)
citation of a high-churn shared-infra module and suggests re-citing it at
`path:Symbol` granularity. Only a symbol-qualified citation is enforceable by
the deterministic citation gate (`adr_citation_resolve.unresolved_citations`),
so the nudge is what walks an ADR from "mentions this file" toward "anchors
this decision to this symbol".

Pure authoring aid: it changes no enforcement behaviour and is never a gate.
Its one consumer is the offline generator
`arch.generators.adr_cross_reference`, which renders it as a soft section of
`docs/arch/generated/adr_xref.md`.

**History (#11600).** This module was the pure drift engine behind
`AdrTouchpointAuditorLoop` (ADR-0056): `compute_drift`, `compute_drift_by_adr`,
`partition_fleet_drift`, and their `DriftFinding`/`AdrRollupEntry`/
`FleetDriftBatch` shapes intersected an ADR's citations with a merged PR's file
diff. That activity-based signal ran ~70% false positives and was retired by
#10540 in favour of the deterministic cited-symbol CI gate; ADR-0136 deleted the
loops and the engine. The shared-infra allowlist survived because the nudge —
its other consumer — is the on-ramp to the citations the new gate can enforce.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from adr_index import ADR


# High-churn modules bare-cited (file-granular) as a *dependency pointer* by
# their pattern ADRs — "the implementation lives here", not "this exact decision
# is this file". An ADR that genuinely *owns* a symbol in one of these should
# cite it at ``:Symbol`` granularity (``src/config.py:HydraFlowConfig``,
# ``src/pr_manager.py:PRManager.upload_screenshot_gist``) — which is what
# :func:`bare_infra_citation_nudges` recommends, and what makes the citation
# enforceable by ``adr_citation_resolve``.
#
# Lineage: the set was grown while it drove drift *suppression* for the retired
# ADR-0056 auditor (#9176 → #9397 → the dashboard/contract clusters → #10455's
# review path + base loop). It is kept as-is under ADR-0136: the same modules
# that were too churn-heavy to drift on are the ones whose bare citations are
# worth nudging to symbol granularity.
_SHARED_INFRA_MODULES = frozenset(
    {
        "src/config.py",
        "src/models.py",
        "src/ports.py",
        "src/post_merge_handler.py",
        "src/pr_manager.py",
        # Dashboard / server / multi-repo startup surface — cross-cutting,
        # bare-cited as a dependency by the dashboard + multi-repo ADRs
        # (0007/0008/0013/0019/0038/0050/0060/0090).
        "src/dashboard.py",
        "src/server.py",
        "src/repo_runtime.py",
        # Contract-testing subsystem — bare-cited as dependency pointers by
        # ADR-0047 (the pattern) and ADR-0052; cassettes/recorders evolve on
        # normal contract churn that does not change either decision.
        "src/contract_recording.py",
        "src/contract_diff.py",
        "src/contract_refresh_loop.py",
        # Review pipeline + base-loop dependency-pointer citations — high-churn
        # implementation surface many review/loop ADRs bare-cite (#10455;
        # base-loop FP class #10441/#10443).
        "src/review_advisor.py",
        "src/review_phase/_phase.py",
        "src/base_background_loop.py",
    }
)


def _is_shared_infra(path: str) -> bool:
    """Is a *bare* citation to *path* a high-churn shared-infra dependency pointer?

    Single source of truth for the one remaining question the allowlist answers.
    The churn-derived fan-out branch that used to OR into this predicate (#10456,
    `config.adr_drift_shared_infra_fanout_threshold`) went with the auditor loop
    under ADR-0136: its only supplier was `compute_drift`, and the offline nudge
    generator deliberately passes no config so the artifact stays deterministic.
    """
    return path in _SHARED_INFRA_MODULES


@dataclass(frozen=True)
class CitationNudge:
    """A non-blocking authoring nudge (#10458).

    ADR *adr_number* bare-cites *path*, a high-churn shared-infra module, so the
    citation is a dependency pointer rather than a decision anchor (see
    :func:`_is_shared_infra`) and nothing enforces it. If the ADR genuinely owns
    a specific symbol there, re-citing it at *suggestion* granularity
    (``path:Symbol``) puts it under the ADR-0136 citation gate, which fails CI
    the moment that symbol is renamed or removed.

    Pure authoring aid: it changes no enforcement behaviour and is never a CI
    gate — it is surfaced only as a soft section in the generated ADR
    cross-reference report.
    """

    adr_number: int
    path: str
    suggestion: str


def bare_infra_citation_nudges(adrs: Iterable[ADR]) -> list[CitationNudge]:
    """Flag every bare citation of a shared-infra module for a ``:Symbol`` nudge.

    Returns one :class:`CitationNudge` per ``(ADR, path)`` pair where the ADR
    bare-cites (empty cited-symbol set) a ``src/`` module :func:`_is_shared_infra`
    treats as a dependency pointer.

    Scoped to **live** (Accepted/Proposed) ADRs (#10565), matching the population
    ``adr_citation_resolve.unresolved_citations`` enforces: a Superseded ADR's
    citations are frozen history that may legitimately point at removed code, so
    nudging its author to re-cite would be noise.

    Output is sorted by ``(adr_number, path)`` for deterministic rendering.
    """
    nudges: list[CitationNudge] = []
    for adr in (a for a in adrs if a.is_live):
        for path, cited_symbols in adr.source_symbols.items():
            # Symbol-qualified citations are already enforceable — leave them.
            if cited_symbols:
                continue
            # The shared-infra rule is scoped to ``src/`` modules.
            if not path.startswith("src/"):
                continue
            if not _is_shared_infra(path):
                continue
            nudges.append(
                CitationNudge(
                    adr_number=adr.number,
                    path=path,
                    suggestion=f"{path}:<Symbol>",
                )
            )
    nudges.sort(key=lambda n: (n.adr_number, n.path))
    return nudges
