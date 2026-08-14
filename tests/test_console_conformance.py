"""Unit ring + live-tree check for scripts/check_console_conformance.py (ARCH-0001 gate)."""

from __future__ import annotations

from pathlib import Path

from scripts.check_console_conformance import collect_errors

RECORD = """# ARCH-0001: test

**Date:** 2026-07-31 · **Seats:** operator · **Verdict:** ACCEPT
**Dissent:** none
**Enforcement:** decision-of-record
**Evidence:** none
"""

PERSONA = """---
name: sample
authority: proposal-only
feeds: verdicts
---
body
"""


def _scaffold(root: Path) -> None:
    agents = root / "agents"
    for sub in (
        "console/decisions/arch",
        "console/decisions/design",
        "console/decisions/general",
    ):
        (agents / sub).mkdir(parents=True)
    (agents / "sample.md").write_text(PERSONA)
    (agents / "console" / "design.md").write_text(
        "# Design Console\n\n**Chair:** product-manager · seats\n"
    )
    (agents / "console" / "arch.md").write_text(
        "# Architecture Console\n\n**Chair:** senior-principal · seats\n"
    )
    (agents / "console" / "README.md").write_text(
        "| **General** | vp-eng | calibration | here |\n"
    )
    (agents / "console" / "decisions" / "arch" / "0001-test.md").write_text(RECORD)


def test_conformant_tree_passes(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    assert collect_errors(tmp_path, check_git=False) == []


def test_missing_enforcement_fails(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    rec = tmp_path / "agents/console/decisions/arch/0001-test.md"
    rec.write_text(RECORD.replace("**Enforcement:** decision-of-record\n", ""))
    errors = collect_errors(tmp_path, check_git=False)
    assert any("Enforcement" in e for e in errors)


def test_enforced_requires_named_check(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    rec = tmp_path / "agents/console/decisions/arch/0001-test.md"
    rec.write_text(RECORD.replace("decision-of-record", "enforced"))
    errors = collect_errors(tmp_path, check_git=False)
    assert any("Enforced by" in e for e in errors)


def test_numbering_gap_fails(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    (tmp_path / "agents/console/decisions/arch/0003-gap.md").write_text(RECORD)
    errors = collect_errors(tmp_path, check_git=False)
    assert any("not contiguous" in e for e in errors)


def test_wrong_chair_fails(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    (tmp_path / "agents/console/design.md").write_text(
        "# Design Console\n\n**Chair:** vp-eng · seats\n"
    )
    errors = collect_errors(tmp_path, check_git=False)
    assert any("chartered chair" in e for e in errors)


def test_staleness_needle_trips_at_six(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run = RECORD.replace("operator", "sample (persona run)")
    for i in range(2, 8):
        (tmp_path / f"agents/console/decisions/arch/{i:04d}-run.md").write_text(run)
    errors = collect_errors(tmp_path, check_git=False)
    assert any("calibration stale" in e for e in errors)


def test_repo_ledger_is_conformant() -> None:
    """The live agents/ tree passes the gate (git immutability checked by the
    make target locally; skipped here so shallow CI clones cannot false-pass)."""
    repo_root = Path(__file__).resolve().parent.parent
    assert collect_errors(repo_root, check_git=False) == []


def test_ci_audit_job_runs_console_conformance() -> None:
    """#11110 (sampled-audit upheld): ARCH-0001 markets ledger immutability
    as `Enforced by: make console-conformance`, but no CI job invoked it —
    the git-history check needs a full clone, so `test_repo_ledger_is_
    conformant` above deliberately passes check_git=False. The enforcement
    lives as a step in the audit job (the one job with fetch-depth: 0);
    pin it so the claim can never silently go false again."""
    import yaml

    repo_root = Path(__file__).resolve().parent.parent
    ci = yaml.safe_load(
        (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    audit_steps = ci["jobs"]["audit"]["steps"]
    conformance_runs = [
        step
        for step in audit_steps
        if "make console-conformance" in str(step.get("run", ""))
    ]
    assert conformance_runs, (
        "the audit job must run `make console-conformance` — it is the only "
        "job with a full-history clone, and without it the ledger's "
        "immutability guarantee is enforced nowhere (#11110)"
    )
    checkout = next(s for s in audit_steps if "checkout" in str(s.get("uses", "")))
    assert checkout.get("with", {}).get("fetch-depth") == 0, (
        "audit job checkout must keep fetch-depth: 0 — the immutability "
        "check reads real git history and false-passes on a shallow clone"
    )
