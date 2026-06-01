"""Production bridge for GateActivatorLoop's detector (ADR-0082, Slice 4).

Wires repo paths to the pure detector in :mod:`scripts.gates.activation`: load
the contract, index the workflow jobs, read the Makefile, and return the planned
gates whose protected surface now exists. Kept separate from the loop (which
owns scheduling/dedup/issue-filing) so the detection core is unit-testable on
its own, mirroring ``branch_protection_audit.audit_repo`` for Slice 5.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.gates.activation import ActivationProposal

_CONTRACT_REL = Path("docs/standards/branch_protection/gates.toml")
_WORKFLOWS_REL = Path(".github/workflows")
_MAKEFILE_REL = Path("Makefile")


def check_gate_activation(repo_root: Path) -> list[ActivationProposal]:
    """Planned gates in ``repo_root`` whose protected surface now exists.

    Returns an empty list when the contract is absent or every gate is already
    active (the steady state). Pure read-only file IO; the caller offloads it
    to a thread so the event loop is not stalled.
    """
    from scripts.gates.activation import activatable_gates  # noqa: PLC0415
    from scripts.gates.contract import load_gates  # noqa: PLC0415
    from scripts.gates.workflow_jobs import index_workflow_jobs  # noqa: PLC0415

    contract_path = repo_root / _CONTRACT_REL
    if not contract_path.exists():
        return []
    contract = load_gates(contract_path)
    job_index = index_workflow_jobs(repo_root / _WORKFLOWS_REL)
    makefile = repo_root / _MAKEFILE_REL
    makefile_text = makefile.read_text() if makefile.exists() else ""
    return activatable_gates(contract, job_index, makefile_text)
