"""FakeGitHub classic branch-protection seed surface (#10148).

``branch_protection_audit.undeclared_legacy_contexts`` compares the LIVE
effective required-check set (ruleset UNION classic branch-protection) to the
declarative contract, catching an undeclared legacy branch-protection layer
that stacks extra required checks on top of (or instead of) the generated
ruleset. In production the classic-protection fetch is
``gh_fetch_legacy_protection`` — a ``gh api /repos/{repo}/branches/{branch}/
protection`` shell-out that is unreachable on the air-gapped sandbox network.
``FakeGitHub.fetch_legacy_protection`` is the sync mirror that serves seeded
state instead, so a sandbox / scenario auditor run can observe the drift (or a
clean audit) without a real network fetch. These tests pin the seed surface
and prove the Fake fetcher is directly injectable into ``audit_repo`` — the
seam a branch_protection_auditor scenario needs to reproduce the exact
documented drift: a legacy layer on staging requiring 5 main-only contexts.
"""

from __future__ import annotations

import json
from pathlib import Path

from branch_protection_audit import audit_repo
from mockworld.fakes import FakeGitHub

_CANONICAL_DIR = (
    Path(__file__).resolve().parents[1] / "docs" / "standards" / "branch_protection"
)

# The exact undeclared-legacy-layer drift from #10148.
_LEGACY_LAYER_CONTEXTS = [
    "Tests",
    "Type Check",
    "quality (.)",
    "Architecture Check",
    "Lint & Format",
]


def _canonical(name: str) -> dict:
    return json.loads((_CANONICAL_DIR / name).read_text())


def test_fetch_legacy_protection_empty_by_default() -> None:
    gh = FakeGitHub()
    assert gh.fetch_legacy_protection("owner/repo", "staging") is None


def test_add_legacy_protection_seed_helper() -> None:
    gh = FakeGitHub()
    gh.add_legacy_protection(
        "staging", {"required_status_checks": {"contexts": ["Tests"]}}
    )

    assert gh.fetch_legacy_protection("owner/repo", "staging") == {
        "required_status_checks": {"contexts": ["Tests"]}
    }
    # Unseeded branches stay clean (None, not an empty dict).
    assert gh.fetch_legacy_protection("owner/repo", "main") is None


def test_fetch_legacy_protection_returns_copies_not_internal_state() -> None:
    """Mutating the served dict must not corrupt the Fake's seeded state."""
    gh = FakeGitHub()
    gh.add_legacy_protection(
        "staging", {"required_status_checks": {"contexts": ["Tests"]}}
    )

    served = gh.fetch_legacy_protection("owner/repo", "staging")
    assert served is not None
    served["required_status_checks"]["contexts"].append("injected")

    assert gh.fetch_legacy_protection("owner/repo", "staging") == {
        "required_status_checks": {"contexts": ["Tests"]}
    }


def test_fake_fetchers_reproduce_the_documented_5_context_legacy_drift() -> None:
    """The seam a branch_protection_auditor scenario needs: seed live rulesets
    matching canonical (no ruleset drift) plus an undeclared legacy layer on
    staging, run the real audit engine, and get a non-clean report naming the
    5 undeclared contexts — no network required."""
    gh = FakeGitHub()
    gh.add_ruleset("main protect", _canonical("main_ruleset.json"))
    gh.add_ruleset("staging protect", _canonical("staging_ruleset.json"))
    gh.add_legacy_protection(
        "staging",
        {"required_status_checks": {"contexts": _LEGACY_LAYER_CONTEXTS}},
    )

    report = audit_repo(
        "owner/repo",
        _CANONICAL_DIR,
        fetch_rulesets=gh.fetch_rulesets,
        fetch_legacy_protection=gh.fetch_legacy_protection,
    )

    assert not report.clean
    joined = "\n".join(report.drifts)
    for ctx in _LEGACY_LAYER_CONTEXTS:
        assert ctx in joined


def test_fake_fetchers_clean_when_no_legacy_layer_seeded() -> None:
    """Seeding the canonical rulesets verbatim with no legacy layer yields a
    clean audit — the seam must not manufacture drift on its own."""
    gh = FakeGitHub()
    gh.add_ruleset("main protect", _canonical("main_ruleset.json"))
    gh.add_ruleset("staging protect", _canonical("staging_ruleset.json"))

    report = audit_repo(
        "owner/repo",
        _CANONICAL_DIR,
        fetch_rulesets=gh.fetch_rulesets,
        fetch_legacy_protection=gh.fetch_legacy_protection,
    )

    assert report.clean, report.drifts
