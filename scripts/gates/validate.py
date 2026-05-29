"""Validate that every active gate maps to a real workflow job.

This is the concrete form of HydraFlow's "do not lie about enforcement
boundaries" doctrine: a required check context that no workflow produces would
block PRs forever (or, worse, silently never run). ``validate`` fails CI before
such a context can be encoded as required.
"""

from __future__ import annotations

from scripts.gates.contract import Contract


def validate(contract: Contract, job_index: set[tuple[str, str]]) -> list[str]:
    """Return one message per active gate whose producer is not a real job."""
    violations: list[str] = []
    for g in contract.gates:
        if g.status != "active":
            continue
        if (g.workflow, g.job) not in job_index:
            violations.append(
                f"gate {g.name!r} declares producer {g.workflow}:{g.job} "
                f"which is not defined under jobs: in that workflow"
            )
    return violations
