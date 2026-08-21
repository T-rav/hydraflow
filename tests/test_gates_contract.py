"""Shape tests for the branch-protection gate contract (gates.toml)."""

from pathlib import Path

from scripts.gates.contract import load_gates

CONTRACT = Path("docs/standards/branch_protection/gates.toml")


def test_contract_has_no_adr_gate() -> None:
    # ADR gate's producing workflow was deleted (commit 29f26763); enforcement
    # moved to the adr_touchpoint_auditor caretaker loop (ADR-0056).
    contract = load_gates(CONTRACT)
    names = {g.name for g in contract.gates}
    assert "ADR gate" not in names


def test_contract_main_requires_fourteen_contexts() -> None:
    contract = load_gates(CONTRACT)
    main = [
        g for g in contract.gates if "main" in g.required_on and g.status == "active"
    ]
    assert len(main) == 14


def test_contract_staging_requires_baseline_plus_ci_gate() -> None:
    contract = load_gates(CONTRACT)
    staging = [
        g for g in contract.gates if "staging" in g.required_on and g.status == "active"
    ]
    # "CI Gate" is the aggregate ci-gate job that blocks red staging PRs
    # (incident #10672); it must be declared so a reconcile can't strip it.
    assert {g.name for g in staging} == {
        "Detect Changes",
        "discover-projects",
        "CI Gate",
    }


def test_branch_envelopes_present() -> None:
    contract = load_gates(CONTRACT)
    assert set(contract.branches) == {"main", "staging"}
    assert contract.branches["main"].allowed_merge_methods == ["merge"]
    assert contract.branches["staging"].allowed_merge_methods == ["squash", "merge"]
    assert contract.branches["main"].code_quality_severity == "errors"
    assert contract.branches["staging"].code_quality_severity is None


def test_unattributed_changes_approval_defaults_true_and_parses_explicit(
    tmp_path,
) -> None:
    toml = tmp_path / "gates.toml"
    toml.write_text(
        '[branch.main]\nallowed_merge_methods = ["merge"]\n'
        '[branch.staging]\nallowed_merge_methods = ["squash"]\n'
        "require_extra_approval_for_unattributed_changes = false\n"
    )
    contract = load_gates(toml)
    assert (
        contract.branches["main"].require_extra_approval_for_unattributed_changes
        is True
    )
    assert (
        contract.branches["staging"].require_extra_approval_for_unattributed_changes
        is False
    )
