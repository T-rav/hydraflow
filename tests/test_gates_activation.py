"""Tests for the gate-activation detector (ADR-0082, Slice 4).

A ``planned`` gate becomes activatable when the surface it protects exists:
its producing ``(workflow, job)`` is defined, its ``make_target`` (if any) is a
real Makefile target, and it binds to the repo's languages/capabilities. The
detector proposes flipping such gates to ``active``.
"""

from pathlib import Path

from scripts.gates.activation import ActivationProposal, activatable_gates
from scripts.gates.contract import BranchEnvelope, Contract, Gate, RepoProfile

_JOBS = {("ci.yml", "browser")}
_MAKE = "test-browser:\n\techo hi\n"


def _gate(
    name: str,
    *,
    status: str = "planned",
    workflow: str = "ci.yml",
    job: str = "browser",
    make_target: str = "test-browser",
    languages: list[str] | None = None,
    requires_capability: list[str] | None = None,
    required_on: list[str] | None = None,
) -> Gate:
    return Gate(
        name=name,
        dimension="browser-e2e",
        tier="extra",
        required_on=required_on if required_on is not None else ["main"],
        runs_on=["rc"],
        languages=languages if languages is not None else [],
        requires_capability=requires_capability
        if requires_capability is not None
        else [],
        status=status,
        workflow=workflow,
        job=job,
        make_target=make_target,
    )


def _contract(gates: list[Gate], repo: RepoProfile | None = None) -> Contract:
    return Contract(
        gates=gates,
        branches={"main": BranchEnvelope(name="main", allowed_merge_methods=["merge"])},
        repo=repo,
    )


def test_planned_gate_with_present_producer_and_target_is_activatable() -> None:
    contract = _contract([_gate("Browser Scenarios")])
    proposals = activatable_gates(contract, _JOBS, _MAKE)
    assert [p.name for p in proposals] == ["Browser Scenarios"]


def test_active_gate_is_never_proposed() -> None:
    contract = _contract([_gate("Browser Scenarios", status="active")])
    assert activatable_gates(contract, _JOBS, _MAKE) == []


def test_planned_gate_missing_producer_is_not_activatable() -> None:
    contract = _contract([_gate("Browser Scenarios")])
    # Producer job not yet defined → surface does not exist.
    assert activatable_gates(contract, set(), _MAKE) == []


def test_planned_gate_missing_make_target_is_not_activatable() -> None:
    contract = _contract([_gate("Browser Scenarios")])
    assert activatable_gates(contract, _JOBS, "other:\n\techo hi\n") == []


def test_planned_gate_with_empty_make_target_only_needs_producer() -> None:
    contract = _contract([_gate("Browser Scenarios", make_target="")])
    proposals = activatable_gates(contract, _JOBS, "")
    assert [p.name for p in proposals] == ["Browser Scenarios"]


def test_language_mismatch_is_not_activatable() -> None:
    contract = _contract(
        [_gate("Browser Scenarios", languages=["go"])],
        repo=RepoProfile(languages=["python"], capabilities=[]),
    )
    assert activatable_gates(contract, _JOBS, _MAKE) == []


def test_capability_mismatch_is_not_activatable() -> None:
    contract = _contract(
        [_gate("Browser Scenarios", requires_capability=["ghas"])],
        repo=RepoProfile(languages=["python"], capabilities=[]),
    )
    assert activatable_gates(contract, _JOBS, _MAKE) == []


def test_capability_match_is_activatable() -> None:
    contract = _contract(
        [_gate("Browser Scenarios", requires_capability=["ghas"])],
        repo=RepoProfile(languages=["python"], capabilities=["ghas"]),
    )
    proposals = activatable_gates(contract, _JOBS, _MAKE)
    assert [p.name for p in proposals] == ["Browser Scenarios"]


def test_repo_none_does_not_filter() -> None:
    contract = _contract([_gate("Browser Scenarios", languages=["go"])], repo=None)
    proposals = activatable_gates(contract, _JOBS, _MAKE)
    assert [p.name for p in proposals] == ["Browser Scenarios"]


def test_proposals_are_sorted_by_name() -> None:
    contract = _contract([_gate("Zeta"), _gate("Alpha")])
    proposals = activatable_gates(contract, _JOBS, _MAKE)
    assert [p.name for p in proposals] == ["Alpha", "Zeta"]


def test_proposal_carries_gate_metadata() -> None:
    contract = _contract([_gate("Browser Scenarios", required_on=["main", "staging"])])
    (proposal,) = activatable_gates(contract, _JOBS, _MAKE)
    assert isinstance(proposal, ActivationProposal)
    assert proposal.dimension == "browser-e2e"
    assert proposal.required_on == ("main", "staging")
    assert proposal.workflow == "ci.yml"
    assert proposal.job == "browser"
    assert proposal.make_target == "test-browser"


def test_empty_required_on_is_not_activatable() -> None:
    # Activating a gate that is required on no branch enforces nothing, so it
    # is not a meaningful proposal.
    contract = _contract([_gate("Browser Scenarios", required_on=[])])
    assert activatable_gates(contract, _JOBS, _MAKE) == []


def test_real_contract_has_no_activatable_gates() -> None:
    # Steady state: this mature repo's gates are all active, so the detector
    # proposes nothing. Activation is the growth mechanism for younger repos.
    from scripts.gates.contract import load_gates
    from scripts.gates.workflow_jobs import index_workflow_jobs

    contract = load_gates(Path("docs/standards/branch_protection/gates.toml"))
    index = index_workflow_jobs(Path(".github/workflows"))
    makefile = Path("Makefile").read_text()
    proposals = activatable_gates(contract, index, makefile)
    # If this fails, someone added a `planned` gate whose surface already
    # exists — activate it in gates.toml rather than deleting this test.
    assert proposals == [], f"unexpected activatable gates: {proposals!r}"
