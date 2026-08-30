"""Shape tests for the branch-protection gate contract (gates.toml)."""

from pathlib import Path

from scripts.gates.contract import load_gates

CONTRACT = Path("docs/standards/branch_protection/gates.toml")


def test_contract_has_no_adr_gate() -> None:
    # ADR gate's producing workflow was deleted (commit 29f26763). Enforcement
    # went to the adr_touchpoint_auditor caretaker loop (ADR-0056), and from
    # there — that loop being retired — into the existing Tests lane as
    # test_no_unresolved_adr_citations (ADR-0136). Still not a gate of its own.
    contract = load_gates(CONTRACT)
    names = {g.name for g in contract.gates}
    assert "ADR gate" not in names


def test_contract_main_requires_the_umbrella_and_the_rc_gates() -> None:
    """`main` is gated by the CI Gate umbrella plus the RC-promotion checks.

    Asserts the SET, not a count. This test was
    ``test_contract_main_requires_fourteen_contexts`` and pinned ``== 14``,
    which says nothing about WHICH contexts and rots on any change to the
    contract — including #11727's, which replaced ten individually-enumerated
    lanes with the umbrella that fans all of them in via ``needs:`` (and five
    more main never required).
    """
    contract = load_gates(CONTRACT)
    main = {
        g.name
        for g in contract.gates
        if "main" in g.required_on and g.status == "active"
    }
    assert main == {
        "CI Gate",
        "Resolve RC PR",
        "Browser Scenarios",
        "Trust Gate (adversarial corpus, fixture mode)",
        "Sandbox (rc/* promotion PR full suite)",
    }


def test_contract_staging_requires_baseline_plus_ci_gate() -> None:
    contract = load_gates(CONTRACT)
    staging = [
        g for g in contract.gates if "staging" in g.required_on and g.status == "active"
    ]
    # "CI Gate" is the aggregate ci-gate job that blocks red staging PRs
    # (incident #10672); it must be declared so a reconcile can't strip it.
    # The two `quality (<dir>)` matrix legs are declared here rather than on
    # main (#11727): they are no-ops that gate nothing, but they are DYNAMIC
    # matrix contexts, and `test_required_matrix_contexts` needs them required
    # somewhere to keep watching for an orphaned leg.
    assert {g.name for g in staging} == {
        "Detect Changes",
        "discover-projects",
        "CI Gate",
        "quality (.)",
        "quality (src/ui)",
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
