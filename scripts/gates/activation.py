"""Detect planned gates whose protected surface now exists (ADR-0082, Slice 4).

A gate authored as ``status = "planned"`` is a guardrail the repo intends to
enforce once the surface it protects exists. This module finds the planned
gates that have become enforceable — their producing ``(workflow, job)`` is now
defined, their ``make_target`` (if any) is a real Makefile target, and they
bind to the repo's languages/capabilities — and proposes flipping them to
``active``.

This is the "self-enforcing as the repo grows" half of the contract: a young
repo (bootstrapped via :mod:`scripts.gates.bootstrap`) starts with gates marked
planned and activates them as each surface lands (the first browser test, the
first MockWorld scenario, a new language). The proposal is recorded back into
the contract through review (a reviewed issue/PR), never a direct GitHub
ruleset mutation, so git history stays the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.gates.contract import Contract, Gate, RepoProfile
from scripts.gates.resolve import gate_applies
from scripts.gates.validate import makefile_targets


@dataclass(frozen=True)
class ActivationProposal:
    """A planned gate that is now enforceable and should be activated."""

    name: str
    dimension: str
    required_on: tuple[str, ...]
    workflow: str
    job: str
    make_target: str


def _enforceable(
    gate: Gate,
    repo: RepoProfile | None,
    job_index: set[tuple[str, str]],
    targets: set[str],
) -> bool:
    """Whether ``gate``'s protected surface exists for this repo now.

    Three conditions, all required: the gate binds to the repo profile
    (language + capability), its producing job is defined, and its make_target
    (if declared) is a real target. These mirror the active-gate checks in
    :mod:`scripts.gates.validate` and :func:`scripts.gates.resolve.gate_applies`
    so an activated gate cannot then fail validation.
    """
    if not gate_applies(gate, repo):
        return False
    if (gate.workflow, gate.job) not in job_index:
        return False
    return not (gate.make_target and gate.make_target not in targets)


def activatable_gates(
    contract: Contract,
    job_index: set[tuple[str, str]],
    makefile_text: str,
) -> list[ActivationProposal]:
    """Planned gates whose surface now exists, sorted by name.

    Args:
        contract: The parsed gate contract (its ``repo`` profile drives the
            language/capability binding check).
        job_index: ``(workflow_filename, job_key)`` pairs defined under
            ``jobs:`` across the workflows (see
            :func:`scripts.gates.workflow_jobs.index_workflow_jobs`).
        makefile_text: Contents of the Makefile (for the make_target check).

    Returns:
        One :class:`ActivationProposal` per planned-but-now-enforceable gate.
        A planned gate with an empty ``required_on`` is skipped: activating it
        would enforce nothing (``resolve_contexts`` requires the branch be in
        ``required_on``), so proposing it would be a no-op.
    """
    targets = makefile_targets(makefile_text)
    proposals = [
        ActivationProposal(
            name=g.name,
            dimension=g.dimension,
            required_on=tuple(g.required_on),
            workflow=g.workflow,
            job=g.job,
            make_target=g.make_target,
        )
        for g in contract.gates
        if g.status == "planned"
        and g.required_on
        and _enforceable(g, contract.repo, job_index, targets)
    ]
    return sorted(proposals, key=lambda p: p.name)
