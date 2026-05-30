"""Validate that every active gate maps to a real workflow job.

This is the concrete form of HydraFlow's "do not lie about enforcement
boundaries" doctrine: a required check context that no workflow produces would
block PRs forever (or, worse, silently never run). ``validate`` fails CI before
such a context can be encoded as required.
"""

from __future__ import annotations

import re

from scripts.gates.contract import Contract

_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.-]+):")


def validate_make_targets(contract: Contract, makefile_text: str) -> list[str]:
    """Every active gate's (non-empty) make_target must be a real Makefile target.

    The contract advertises ``make_target`` as the single entry point
    (local == CI == pre-commit). A gate pointing at a deleted or misspelled
    target is a silent local/CI divergence; this turns that into a CI failure.
    """
    targets = {
        m.group(1)
        for line in makefile_text.splitlines()
        if (m := _MAKE_TARGET.match(line))
    }
    return [
        f"gate {g.name!r} make_target {g.make_target!r} is not a Makefile target"
        for g in contract.gates
        if g.status == "active" and g.make_target and g.make_target not in targets
    ]


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
