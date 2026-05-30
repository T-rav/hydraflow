"""Capability/language-aware resolution + hard-fail on unsatisfied dimensions."""

from pathlib import Path

from scripts.gates.contract import (
    BranchEnvelope,
    CodeScanningTool,
    Contract,
    Gate,
    RepoProfile,
    load_gates,
)
from scripts.gates.coverage import unsatisfied_dimensions
from scripts.gates.resolve import render_ruleset, resolve_contexts

CONTRACT = Path("docs/standards/branch_protection/gates.toml")


def _gate(name, dimension, *, languages, requires_capability, status="active"):
    return Gate(
        name=name,
        dimension=dimension,
        tier="core",
        required_on=["main"],
        runs_on=["rc"],
        languages=languages,
        requires_capability=requires_capability,
        status=status,
        workflow="ci.yml",
        job="x",
    )


def _contract(gates, repo):
    return Contract(
        gates=gates,
        branches={"main": BranchEnvelope(name="main", allowed_merge_methods=["merge"])},
        repo=repo,
    )


def test_gate_requiring_absent_capability_is_dropped():
    c = _contract(
        [_gate("CodeQL", "sast", languages=["python"], requires_capability=["ghas"])],
        RepoProfile(languages=["python"], capabilities=[]),
    )
    assert resolve_contexts(c, "main") == []


def test_gate_requiring_present_capability_is_kept():
    c = _contract(
        [_gate("CodeQL", "sast", languages=["python"], requires_capability=["ghas"])],
        RepoProfile(languages=["python"], capabilities=["ghas"]),
    )
    assert resolve_contexts(c, "main") == ["CodeQL"]


def test_gate_for_absent_language_is_dropped():
    c = _contract(
        [_gate("npm audit", "dep-cves", languages=["js"], requires_capability=[])],
        RepoProfile(languages=["python"], capabilities=[]),
    )
    assert resolve_contexts(c, "main") == []


def test_dimension_with_only_unavailable_binding_is_unsatisfied():
    # sast offered only via CodeQL (needs ghas); repo lacks ghas and there is no
    # active fallback -> the required sast dimension is unsatisfied (hard-fail).
    c = _contract(
        [
            _gate("CodeQL", "sast", languages=["python"], requires_capability=["ghas"]),
            _gate(
                "Semgrep",
                "sast",
                languages=["python"],
                requires_capability=[],
                status="planned",
            ),
        ],
        RepoProfile(languages=["python"], capabilities=[]),
    )
    assert unsatisfied_dimensions(c, "main") == ["sast"]


def test_dimension_satisfied_by_active_fallback():
    c = _contract(
        [
            _gate("CodeQL", "sast", languages=["python"], requires_capability=["ghas"]),
            _gate("Semgrep", "sast", languages=["python"], requires_capability=[]),
        ],
        RepoProfile(languages=["python"], capabilities=[]),
    )
    assert unsatisfied_dimensions(c, "main") == []
    assert resolve_contexts(c, "main") == ["Semgrep"]


def test_code_scanning_dropped_without_ghas():
    c = _contract([], RepoProfile(languages=["python"], capabilities=[]))
    c.branches["main"] = BranchEnvelope(
        name="main",
        allowed_merge_methods=["merge"],
        code_scanning=[CodeScanningTool("CodeQL", "high_or_higher", "errors")],
    )
    rule_types = {r["type"] for r in render_ruleset(c, "main")["rules"]}
    assert "code_scanning" not in rule_types


# --- the real contract: this repo is python + ghas, so output is unchanged ---


def test_real_contract_declares_repo_profile():
    c = load_gates(CONTRACT)
    assert c.repo is not None
    assert "python" in c.repo.languages
    assert "ghas" in c.repo.capabilities


def test_real_contract_output_unchanged_by_filtering():
    c = load_gates(CONTRACT)
    assert len(resolve_contexts(c, "main")) == 14
    assert resolve_contexts(c, "staging") == ["Detect Changes", "discover-projects"]
    assert unsatisfied_dimensions(c, "main") == []
    assert unsatisfied_dimensions(c, "staging") == []
    # code_scanning (CodeQL) still present because this repo has ghas.
    assert any(r["type"] == "code_scanning" for r in render_ruleset(c, "main")["rules"])
