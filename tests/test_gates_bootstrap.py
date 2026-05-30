"""Tests for init-time gate bootstrap: detect profile -> resolve -> plan."""

import json
from pathlib import Path

from scripts.gates.bootstrap import (
    build_repo_profile,
    gates_plan_section,
    render_repo_profile_toml,
)
from scripts.gates.contract import BranchEnvelope, Contract, Gate, RepoProfile

CONTRACT = Path("docs/standards/branch_protection/gates.toml")


def _gh_meta(meta: dict):
    def fake(*args: str) -> str:
        return json.dumps(meta)

    return fake


def test_build_repo_profile_combines_languages_and_capabilities() -> None:
    profile = build_repo_profile(
        Path("/whatever"),
        "o/r",
        gh=_gh_meta({"private": False}),  # public -> ghas
        detect_langs=lambda _root: {"python", "typescript"},
    )
    assert profile.languages == ["python", "typescript"]
    assert profile.capabilities == ["ghas"]


def test_build_repo_profile_without_slug_has_no_capabilities() -> None:
    profile = build_repo_profile(
        Path("/whatever"), None, gh=_gh_meta({}), detect_langs=lambda _r: {"go"}
    )
    assert profile.languages == ["go"]
    assert profile.capabilities == []


def test_render_repo_profile_toml() -> None:
    toml = render_repo_profile_toml(
        RepoProfile(languages=["python"], capabilities=["ghas"])
    )
    assert "[repo]" in toml
    assert 'languages = ["python"]' in toml
    assert 'capabilities = ["ghas"]' in toml


def test_gates_plan_section_lists_resolved_and_unsatisfied() -> None:
    contract = Contract(
        gates=[
            Gate(
                name="CodeQL",
                dimension="sast",
                tier="core",
                required_on=["main"],
                runs_on=["rc"],
                languages=["python"],
                requires_capability=["ghas"],
                status="active",
                workflow="ci.yml",
                job="x",
            )
        ],
        branches={"main": BranchEnvelope(name="main", allowed_merge_methods=["merge"])},
    )
    # A no-GHAS python repo: CodeQL drops, sast becomes unsatisfied.
    section = "\n".join(
        gates_plan_section(RepoProfile(languages=["python"], capabilities=[]), contract)
    )
    assert "Branch-protection gates" in section
    assert "languages" in section and "python" in section
    assert "sast" in section  # surfaced as unsatisfied
    assert "make gen-gates" in section


def test_gates_plan_section_for_this_repo_lists_main_checks() -> None:
    from scripts.gates.contract import load_gates

    contract = load_gates(CONTRACT)
    section = "\n".join(
        gates_plan_section(
            RepoProfile(languages=["python"], capabilities=["ghas"]), contract
        )
    )
    assert "Tests" in section
    assert "Detect Changes" in section
