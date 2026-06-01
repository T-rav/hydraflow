"""Tests for the gate-activation production bridge (ADR-0082, Slice 4)."""

from __future__ import annotations

from pathlib import Path

from gate_activation_check import check_gate_activation


def test_real_repo_is_steady_state() -> None:
    # This mature repo has all gates active → nothing to propose.
    assert check_gate_activation(Path(".")) == []


def test_missing_contract_returns_empty(tmp_path: Path) -> None:
    # A bare directory with no gates.toml must not raise.
    assert check_gate_activation(tmp_path) == []


def test_planned_gate_with_surface_is_proposed(tmp_path: Path) -> None:
    bp = tmp_path / "docs/standards/branch_protection"
    bp.mkdir(parents=True)
    (bp / "gates.toml").write_text(
        '[repo]\nlanguages = ["python"]\ncapabilities = []\n\n'
        '[branch.main]\nallowed_merge_methods = ["squash"]\n\n'
        "[[gate]]\n"
        'name = "Browser Scenarios"\n'
        'dimension = "browser-e2e"\n'
        'tier = "extra"\n'
        'required_on = ["main"]\n'
        'runs_on = ["rc"]\n'
        'languages = ["python"]\n'
        "requires_capability = []\n"
        'status = "planned"\n'
        'workflow = "ci.yml"\n'
        'job = "browser"\n'
        'make_target = "test-browser"\n'
    )
    wf = tmp_path / ".github/workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "name: ci\non: [push]\njobs:\n  browser:\n    runs-on: x\n"
    )
    (tmp_path / "Makefile").write_text("test-browser:\n\techo hi\n")

    proposals = check_gate_activation(tmp_path)
    assert [p.name for p in proposals] == ["Browser Scenarios"]
