"""Tests for gate->workflow-job validation (the 'no orphan required check' rule)."""

from pathlib import Path

from scripts.gates.contract import BranchEnvelope, Contract, Gate, load_gates
from scripts.gates.validate import validate, validate_make_targets
from scripts.gates.workflow_jobs import index_workflow_jobs


def _gate(
    name: str,
    workflow: str,
    job: str,
    status: str = "active",
    make_target: str = "",
) -> Gate:
    return Gate(
        name=name,
        dimension="d",
        tier="core",
        required_on=["main"],
        runs_on=["rc"],
        languages=["python"],
        requires_capability=[],
        status=status,
        workflow=workflow,
        job=job,
        make_target=make_target,
    )


def _contract(gates: list[Gate]) -> Contract:
    return Contract(
        gates=gates,
        branches={"main": BranchEnvelope(name="main", allowed_merge_methods=["merge"])},
    )


def test_clean_contract_has_no_violations() -> None:
    contract = _contract([_gate("Tests", "ci.yml", "test")])
    assert validate(contract, {("ci.yml", "test")}) == []


def test_orphan_gate_is_a_violation() -> None:
    # The ADR gate failure mode: the producing workflow/job is gone.
    contract = _contract([_gate("ADR gate", "adr-touchpoints.yml", "adr")])
    violations = validate(contract, {("ci.yml", "test")})
    assert len(violations) == 1
    assert "ADR gate" in violations[0]


def test_planned_gate_is_not_validated() -> None:
    contract = _contract([_gate("Future", "nope.yml", "nope", status="planned")])
    assert validate(contract, set()) == []


def test_index_real_workflows_includes_test_job() -> None:
    index = index_workflow_jobs(Path(".github/workflows"))
    assert ("ci.yml", "test") in index


def test_index_matches_both_yml_and_yaml(tmp_path: Path) -> None:
    (tmp_path / "a.yml").write_text("on: [push]\njobs:\n  alpha:\n    runs-on: x\n")
    (tmp_path / "b.yaml").write_text("on: [push]\njobs:\n  beta:\n    runs-on: x\n")
    index = index_workflow_jobs(tmp_path)
    assert ("a.yml", "alpha") in index
    assert ("b.yaml", "beta") in index


def test_real_contract_has_no_orphans() -> None:
    # End-to-end: the committed gates.toml must not declare any orphan producer.
    contract = load_gates(Path("docs/standards/branch_protection/gates.toml"))
    index = index_workflow_jobs(Path(".github/workflows"))
    assert validate(contract, index) == []


def test_make_target_must_exist_in_makefile() -> None:
    contract = _contract([_gate("Tests", "ci.yml", "test", make_target="ghost")])
    assert validate_make_targets(contract, "real:\n\techo hi\n") != []
    assert validate_make_targets(contract, "ghost:\n\techo hi\n") == []


def test_make_target_empty_or_planned_is_skipped() -> None:
    contract = _contract(
        [
            _gate("Active", "ci.yml", "test"),  # empty make_target
            _gate("Planned", "ci.yml", "test", status="planned", make_target="ghost"),
        ]
    )
    assert validate_make_targets(contract, "") == []


def test_real_contract_make_targets_exist() -> None:
    contract = load_gates(Path("docs/standards/branch_protection/gates.toml"))
    assert validate_make_targets(contract, Path("Makefile").read_text()) == []
