"""Tests for the branch-protection audit core (live vs canonical rulesets)."""

from __future__ import annotations

import json
from pathlib import Path

from branch_protection_audit import (
    AuditReport,
    audit_repo,
    diff_ruleset,
    load_canonical,
)

CANONICAL_DIR = Path("docs/standards/branch_protection")


def _with_id(cfg: dict, n: int) -> dict:
    """A live-shaped copy of a canonical ruleset (GitHub adds an id)."""
    out = dict(cfg)
    out["id"] = n
    return out


def test_load_canonical_reads_both_rulesets() -> None:
    canonical = load_canonical(CANONICAL_DIR)
    assert set(canonical) == {"main protect", "staging protect"}


def test_diff_ruleset_clean_when_equal() -> None:
    cfg = json.loads((CANONICAL_DIR / "main_ruleset.json").read_text())
    # GitHub returns the same content plus defaulted fields + an id; those are
    # normalized away, so an equivalent live ruleset shows no drift.
    live = {**cfg, "id": 123, "created_at": "2026-01-01"}
    assert diff_ruleset(cfg, live) == []


def test_diff_ruleset_detects_changed_context() -> None:
    cfg = json.loads((CANONICAL_DIR / "main_ruleset.json").read_text())
    live = json.loads(json.dumps(cfg))  # deep copy
    for rule in live["rules"]:
        if rule["type"] == "required_status_checks":
            rule["parameters"]["required_status_checks"].append({"context": "Rogue"})
    assert diff_ruleset(cfg, live) != []


def test_reordered_required_checks_is_not_drift() -> None:
    # GitHub may return the required-status-check contexts in a different order
    # than canonical; that must NOT read as drift (else the loop false-files).
    cfg = json.loads((CANONICAL_DIR / "main_ruleset.json").read_text())
    live = json.loads(json.dumps(cfg))
    for rule in live["rules"]:
        if rule["type"] == "required_status_checks":
            rule["parameters"]["required_status_checks"].reverse()
    assert diff_ruleset(cfg, live) == []


def test_audit_repo_clean() -> None:
    canonical = load_canonical(CANONICAL_DIR)

    def fetch(_repo: str) -> dict:
        return {name: _with_id(cfg, 1) for name, cfg in canonical.items()}

    report = audit_repo("o/r", CANONICAL_DIR, fetch_rulesets=fetch)
    assert isinstance(report, AuditReport)
    assert report.clean
    assert report.drifts == []


def test_audit_repo_missing_ruleset_is_drift() -> None:
    canonical = load_canonical(CANONICAL_DIR)

    def fetch(_repo: str) -> dict:
        # Live is missing 'staging protect'.
        return {"main protect": _with_id(canonical["main protect"], 1)}

    report = audit_repo("o/r", CANONICAL_DIR, fetch_rulesets=fetch)
    assert not report.clean
    assert any("staging protect" in line for line in report.drifts)


def test_audit_repo_context_drift_is_reported() -> None:
    canonical = load_canonical(CANONICAL_DIR)

    def fetch(_repo: str) -> dict:
        live = {name: _with_id(cfg, 1) for name, cfg in canonical.items()}
        for rule in live["main protect"]["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["required_status_checks"] = [{"context": "Only"}]
        return live

    report = audit_repo("o/r", CANONICAL_DIR, fetch_rulesets=fetch)
    assert not report.clean
    assert any("main protect" in line for line in report.drifts)
