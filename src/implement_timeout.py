"""Complexity-tiered implement timeout (#11568).

``agent_timeout`` (default 3600s) used to be a flat budget for every
implement spawn. The 2026-08-21 throughput analysis found 13 of 153 implement
runs hitting that flat cap — and a complexity-1 issue does not need the same
hour a complexity-5 issue gets. A run that is still going at its tier's
ceiling is a *signal* (the issue is harder than triage scored it, or the
agent is stuck), not a budget to burn again on the next attempt.

The tier is read from triage's ``complexity_score`` (0–10) — the SAME field
the size-tiered plan review (#11304) and lite planning (#11305) key off —
so there is one notion of "how big is this issue" across the pipeline. The
multiplier table below is a module constant rather than config on purpose:
it is a shape, not an operator dial; ``agent_timeout`` stays the single
ceiling and the single knob.

Tier table (fractions of ``agent_timeout``; seconds at the 3600s default):

======================  ========  ==================
``complexity_score``    fraction  default timeout
======================  ========  ==================
unknown / unscored (0)  1.00      3600  (the ceiling)
1–2                     0.50      1800
3–4                     0.75      2700
5–10                    1.00      3600  (the ceiling)
======================  ========  ==================

Unknown reads as the ceiling on purpose (never shrink a budget we have no
evidence for — the same fail-toward-conservative reading #11304's tier gate
uses). The floor mirrors ``HydraFlowConfig.agent_timeout``'s ``ge=60``; the
result never exceeds the ceiling, whatever the table says.
"""

from __future__ import annotations

#: ``(inclusive upper complexity bound, fraction of the ceiling)`` rows, in
#: ascending bound order. Complexity above the last bound gets the ceiling.
IMPLEMENT_TIMEOUT_TIERS: tuple[tuple[int, float], ...] = (
    (2, 0.5),
    (4, 0.75),
)

#: Mirrors ``HydraFlowConfig.agent_timeout``'s lower bound (``ge=60``).
MIN_IMPLEMENT_TIMEOUT_S = 60


def tiered_implement_timeout(complexity: int | None, ceiling: int) -> int:
    """Return the implement spawn timeout for *complexity* under *ceiling*.

    *complexity* is triage's 0–10 ``complexity_score``; ``None``/``0``/
    negative all read as "unknown" and get the full *ceiling* (the flat
    pre-#11568 behaviour). Scored issues get ``ceiling × fraction`` from
    :data:`IMPLEMENT_TIMEOUT_TIERS`, clamped to ``[MIN_IMPLEMENT_TIMEOUT_S,
    ceiling]`` — the floor never pushes the result above the ceiling.
    """
    ceiling = int(ceiling)
    if complexity is None or complexity <= 0:
        return ceiling
    for upper, fraction in IMPLEMENT_TIMEOUT_TIERS:
        if complexity <= upper:
            tiered = int(ceiling * fraction)
            return min(ceiling, max(MIN_IMPLEMENT_TIMEOUT_S, tiered))
    return ceiling
