"""Dimension coverage: which required dimensions have no bindable active gate.

A gate dimension required on a branch must have at least one active gate that is
bindable for the repo (language + capability match). If every candidate is
planned or filtered out (for example SAST offered only via CodeQL on a repo
without GHAS, with no active OSS fallback), the dimension is unsatisfied and the
generator should hard-fail rather than silently drop a guardrail.
"""

from __future__ import annotations

from collections import defaultdict

from scripts.gates.contract import Contract
from scripts.gates.resolve import gate_applies


def unsatisfied_dimensions(contract: Contract, branch: str) -> list[str]:
    """Sorted dimensions required on ``branch`` with no bindable active gate."""
    by_dim: dict[str, list] = defaultdict(list)
    for g in contract.gates:
        if branch in g.required_on:
            by_dim[g.dimension].append(g)
    bad = [
        dim
        for dim, gates in by_dim.items()
        if not any(
            g.status == "active" and gate_applies(g, contract.repo) for g in gates
        )
    ]
    return sorted(bad)
