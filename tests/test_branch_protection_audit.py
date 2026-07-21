"""Tests for the branch-protection audit core (live vs canonical rulesets,
and live-effective-vs-declarative undeclared legacy-layer drift, #10148)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from branch_protection_audit import (
    AuditReport,
    audit_repo,
    diff_ruleset,
    legacy_protection_required_contexts,
    load_canonical,
    ruleset_required_contexts,
    undeclared_legacy_contexts,
)

CANONICAL_DIR = Path("docs/standards/branch_protection")

# The exact undeclared-legacy-layer drift from #10148: a legacy branch-protection
# rule requires 5 contexts on staging that gates.toml declares required_on
# ["main"] only (signal-only on staging per ADR-0042's two-tier model).
_LEGACY_LAYER_CONTEXTS = [
    "Tests",
    "Type Check",
    "quality (.)",
    "Architecture Check",
    "Lint & Format",
]


def _with_id(cfg: dict, n: int) -> dict:
    """A live-shaped copy of a canonical ruleset (GitHub adds an id)."""
    out = dict(cfg)
    out["id"] = n
    return out


def _no_legacy_protection(_repo: str, _branch: str) -> dict[str, Any] | None:
    """Default injectable: no classic branch-protection rule on any branch."""
    return None


def _legacy_protection_for(contexts: list[str]) -> dict[str, Any]:
    """A classic branch-protection API response requiring ``contexts``."""
    return {"required_status_checks": {"strict": False, "contexts": contexts}}


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

    report = audit_repo(
        "o/r",
        CANONICAL_DIR,
        fetch_rulesets=fetch,
        fetch_legacy_protection=_no_legacy_protection,
    )
    assert isinstance(report, AuditReport)
    assert report.clean
    assert report.drifts == []


def test_audit_repo_missing_ruleset_is_drift() -> None:
    canonical = load_canonical(CANONICAL_DIR)

    def fetch(_repo: str) -> dict:
        # Live is missing 'staging protect'.
        return {"main protect": _with_id(canonical["main protect"], 1)}

    report = audit_repo(
        "o/r",
        CANONICAL_DIR,
        fetch_rulesets=fetch,
        fetch_legacy_protection=_no_legacy_protection,
    )
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

    report = audit_repo(
        "o/r",
        CANONICAL_DIR,
        fetch_rulesets=fetch,
        fetch_legacy_protection=_no_legacy_protection,
    )
    assert not report.clean
    assert any("main protect" in line for line in report.drifts)


# --- ruleset_required_contexts ---------------------------------------------


def test_ruleset_required_contexts_extracts_context_names() -> None:
    ruleset = {
        "rules": [
            {"type": "deletion"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "Tests"},
                        {"context": "Lint & Format"},
                    ]
                },
            },
        ]
    }
    assert ruleset_required_contexts(ruleset) == {"Tests", "Lint & Format"}


def test_ruleset_required_contexts_none_ruleset_returns_empty() -> None:
    assert ruleset_required_contexts(None) == set()


def test_ruleset_required_contexts_no_required_status_checks_rule() -> None:
    ruleset = {"rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]}
    assert ruleset_required_contexts(ruleset) == set()


# --- legacy_protection_required_contexts ------------------------------------


def test_legacy_protection_required_contexts_reads_classic_contexts_field() -> None:
    protection = {"required_status_checks": {"contexts": ["Tests", "Lint & Format"]}}
    assert legacy_protection_required_contexts(protection) == {"Tests", "Lint & Format"}


def test_legacy_protection_required_contexts_unions_checks_field() -> None:
    # Newer GitHub responses carry both the deprecated `contexts` (strings) and
    # `checks` ({"context": ..., "app_id": ...}); union both shapes.
    protection = {
        "required_status_checks": {
            "contexts": ["Tests"],
            "checks": [
                {"context": "Tests", "app_id": -1},
                {"context": "Lint & Format"},
            ],
        }
    }
    assert legacy_protection_required_contexts(protection) == {"Tests", "Lint & Format"}


def test_legacy_protection_required_contexts_none_returns_empty() -> None:
    """None means the classic endpoint 404'd — no legacy rule, clean state."""
    assert legacy_protection_required_contexts(None) == set()


def test_legacy_protection_required_contexts_no_required_status_checks_key() -> None:
    assert (
        legacy_protection_required_contexts({"enforce_admins": {"enabled": True}})
        == set()
    )


# --- undeclared_legacy_contexts ---------------------------------------------


def test_undeclared_legacy_contexts_flags_the_documented_5_context_drift() -> None:
    """#10148: a legacy branch-protection layer on staging requires 5 contexts
    gates.toml declares required_on ["main"] only."""
    canonical_staging = json.loads((CANONICAL_DIR / "staging_ruleset.json").read_text())
    live_staging = canonical_staging  # the ruleset itself matches canonical exactly
    legacy = _legacy_protection_for(_LEGACY_LAYER_CONTEXTS)

    undeclared = undeclared_legacy_contexts(canonical_staging, live_staging, legacy)

    assert set(undeclared) == set(_LEGACY_LAYER_CONTEXTS)


def test_undeclared_legacy_contexts_clean_when_live_matches_declarative() -> None:
    canonical_staging = json.loads((CANONICAL_DIR / "staging_ruleset.json").read_text())
    assert undeclared_legacy_contexts(canonical_staging, canonical_staging, None) == []


def test_undeclared_legacy_contexts_clean_when_legacy_is_subset_of_declared() -> None:
    """A legacy rule that only re-requires already-declared contexts is not drift."""
    canonical_main = json.loads((CANONICAL_DIR / "main_ruleset.json").read_text())
    legacy = _legacy_protection_for(["Tests"])  # "Tests" IS required_on main

    assert undeclared_legacy_contexts(canonical_main, canonical_main, legacy) == []


def test_undeclared_legacy_contexts_none_canonical_and_live_treated_as_empty() -> None:
    legacy = _legacy_protection_for(["Rogue"])
    assert undeclared_legacy_contexts(None, None, legacy) == ["Rogue"]


# --- audit_repo: end-to-end undeclared-legacy-layer drift -------------------


def test_audit_repo_detects_5_context_legacy_drift_on_staging() -> None:
    """The exact scenario from #10148: staging's live ruleset matches canonical
    exactly (no ruleset drift), but an undeclared legacy branch-protection
    layer on staging additionally requires 5 main-only contexts."""
    canonical = load_canonical(CANONICAL_DIR)

    def fetch_rulesets(_repo: str) -> dict:
        return {name: _with_id(cfg, 1) for name, cfg in canonical.items()}

    def fetch_legacy_protection(_repo: str, branch: str) -> dict[str, Any] | None:
        if branch == "staging":
            return _legacy_protection_for(_LEGACY_LAYER_CONTEXTS)
        return None

    report = audit_repo(
        "o/r",
        CANONICAL_DIR,
        fetch_rulesets=fetch_rulesets,
        fetch_legacy_protection=fetch_legacy_protection,
    )

    assert not report.clean
    joined = "\n".join(report.drifts)
    for ctx in _LEGACY_LAYER_CONTEXTS:
        assert ctx in joined
    # The already-declared staging baseline must not be flagged as undeclared.
    assert "Detect Changes" not in joined
    assert "discover-projects" not in joined


def test_audit_repo_clean_when_live_matches_declarative_with_no_legacy_layer() -> None:
    """No ruleset drift and no legacy-layer drift => a fully clean report."""
    canonical = load_canonical(CANONICAL_DIR)

    def fetch_rulesets(_repo: str) -> dict:
        return {name: _with_id(cfg, 1) for name, cfg in canonical.items()}

    report = audit_repo(
        "o/r",
        CANONICAL_DIR,
        fetch_rulesets=fetch_rulesets,
        fetch_legacy_protection=_no_legacy_protection,
    )

    assert report.clean
    assert report.drifts == []


def test_audit_repo_legacy_layer_matching_declared_contexts_is_clean() -> None:
    """A legacy rule on main that only re-asserts already-declared contexts
    (e.g. an operator's belt-and-suspenders classic rule mirroring the
    ruleset) must not read as drift."""
    canonical = load_canonical(CANONICAL_DIR)
    main_contexts = sorted(ruleset_required_contexts(canonical["main protect"]))

    def fetch_rulesets(_repo: str) -> dict:
        return {name: _with_id(cfg, 1) for name, cfg in canonical.items()}

    def fetch_legacy_protection(_repo: str, branch: str) -> dict[str, Any] | None:
        if branch == "main":
            return _legacy_protection_for(main_contexts)
        return None

    report = audit_repo(
        "o/r",
        CANONICAL_DIR,
        fetch_rulesets=fetch_rulesets,
        fetch_legacy_protection=fetch_legacy_protection,
    )

    assert report.clean
