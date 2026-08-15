"""Unit ring + live-tree check for scripts/check_console_conformance.py (ARCH-0001 gate)."""

from __future__ import annotations

from pathlib import Path

from scripts.check_console_conformance import (
    _COMMIT_MARK,
    _is_record_path,
    _ledger_change_argv,
    _parse_ledger_changes,
    collect_errors,
)

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
    lives as a step in the audit job (a job with fetch-depth: 0); pin it so
    the claim can never silently go false again.

    This only pins that the step exists in the job's step list — it does not
    evaluate whether the job's `if:` actually fires for a given changeset.
    That reachability question is a separate, sharper failure mode (#11164:
    the step existed here but the job never ran for an agents/**-only PR,
    which is the exact scenario #11110 was filed against) and is pinned in
    tests/regressions/test_issue_11164.py.
    """
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
        "the audit job must run `make console-conformance` — without it the "
        "ledger's immutability guarantee is enforced nowhere (#11110)"
    )
    checkout = next(s for s in audit_steps if "checkout" in str(s.get("uses", "")))
    assert checkout.get("with", {}).get("fetch-depth") == 0, (
        "audit job checkout must keep fetch-depth: 0 — the immutability "
        "check reads real git history and false-passes on a shallow clone"
    )


# --- Check #6 helpers: pure unit ring (no subprocess) ----------------------
# Integration-level base-resolution / real-git behavior is covered in
# tests/regressions/test_issue_11169.py.


def test_is_record_path_accepts_numbered_record() -> None:
    assert _is_record_path("agents/console/decisions/arch/0001-test.md") is True


def test_is_record_path_rejects_readme() -> None:
    assert _is_record_path("agents/console/decisions/arch/README.md") is False


def test_is_record_path_rejects_non_markdown() -> None:
    assert _is_record_path("agents/console/decisions/arch/0001-test.txt") is False


def test_ledger_change_argv_covers_delete_modify_rename() -> None:
    argv = _ledger_change_argv("agents/console/decisions", "deadbeef")
    assert "-M" in argv
    assert "--diff-filter=DMR" in argv
    assert "--no-merges" not in argv, (
        "excluding merge commits would silently hide a record modification "
        "delivered via a merge commit inside the PR's own range"
    )
    assert "deadbeef..HEAD" in argv
    assert argv[-2:] == ["--", "agents/console/decisions"]


def test_parse_ledger_changes_modified_record() -> None:
    known = {"agents/console/decisions/arch/0001-test.md"}
    log = f"{_COMMIT_MARK}abc123 fix: typo\nM\tagents/console/decisions/arch/0001-test.md\n"
    violations = _parse_ledger_changes(log, known)
    assert len(violations) == 1
    assert "0001-test.md" in violations[0]
    assert "modified" in violations[0]
    assert "abc123" in violations[0]


def test_parse_ledger_changes_deleted_record() -> None:
    known = {"agents/console/decisions/arch/0001-test.md"}
    log = f"{_COMMIT_MARK}abc123 rm: cleanup\nD\tagents/console/decisions/arch/0001-test.md\n"
    violations = _parse_ledger_changes(log, known)
    assert len(violations) == 1
    assert "deleted" in violations[0]


def test_parse_ledger_changes_renamed_record() -> None:
    known = {"agents/console/decisions/arch/0001-test.md"}
    log = (
        f"{_COMMIT_MARK}abc123 mv: relocate\n"
        "R100\tagents/console/decisions/arch/0001-test.md\t"
        "agents/console/decisions/design/0001-test.md\n"
    )
    violations = _parse_ledger_changes(log, known)
    assert len(violations) == 1
    assert "renamed" in violations[0]
    assert "arch/0001-test.md" in violations[0]
    assert "design/0001-test.md" in violations[0]


def test_parse_ledger_changes_multiple_commits_attributed_separately() -> None:
    known = {
        "agents/console/decisions/arch/0001-test.md",
        "agents/console/decisions/arch/0002-test.md",
    }
    log = (
        f"{_COMMIT_MARK}aaa111 fix: amend one\n"
        "M\tagents/console/decisions/arch/0001-test.md\n"
        f"{_COMMIT_MARK}bbb222 fix: amend two\n"
        "M\tagents/console/decisions/arch/0002-test.md\n"
    )
    violations = _parse_ledger_changes(log, known)
    assert len(violations) == 2
    joined = "\n".join(violations)
    assert "0001-test.md" in joined and "aaa111" in joined
    assert "0002-test.md" in joined and "bbb222" in joined


def test_parse_ledger_changes_empty_log_yields_no_violations() -> None:
    assert (
        _parse_ledger_changes("", {"agents/console/decisions/arch/0001-test.md"}) == []
    )


def test_parse_ledger_changes_ignores_path_not_in_known_records() -> None:
    # A record created and then typo-fixed within the same PR is not part of
    # the merge-base record set — this is the false-positive the original
    # issue (#11169) was filed against.
    known: set[str] = set()
    log = f"{_COMMIT_MARK}abc123 fix: typo\nM\tagents/console/decisions/arch/0002-new.md\n"
    assert _parse_ledger_changes(log, known) == []


def test_parse_ledger_changes_ignores_added_status_defensively() -> None:
    known = {"agents/console/decisions/arch/0001-test.md"}
    log = f"{_COMMIT_MARK}abc123 feat: new record\nA\tagents/console/decisions/arch/0001-test.md\n"
    assert _parse_ledger_changes(log, known) == []
