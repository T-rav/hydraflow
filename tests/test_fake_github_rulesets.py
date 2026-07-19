"""FakeGitHub branch-protection ruleset seed surface (#9644, ADR-0082).

``BranchProtectionAuditorLoop`` audits live GitHub rulesets against the
canonical contract by injecting a ``fetch_rulesets`` callable into
``branch_protection_audit.audit_repo``. In production that callable is
``gh_fetch_rulesets`` — a ``gh api /repos/{repo}/rulesets`` shell-out that is
unreachable on the air-gapped sandbox network. ``FakeGitHub.fetch_rulesets`` is
the sync mirror that serves seeded ruleset state instead, so a sandbox /
scenario auditor run can observe drift (or a clean audit) without a real
network fetch. These tests pin the seed surface and prove the Fake fetcher is
directly injectable into ``audit_repo`` — the seam the s41 scenario needs.
"""

from __future__ import annotations

import json
from pathlib import Path

from branch_protection_audit import audit_repo
from mockworld.fakes import FakeGitHub
from mockworld.seed import MockWorldSeed

_CANONICAL_DIR = (
    Path(__file__).resolve().parents[1] / "docs" / "standards" / "branch_protection"
)


def _canonical(name: str) -> dict:
    return json.loads((_CANONICAL_DIR / name).read_text())


def _drifted_staging() -> dict:
    """The staging ruleset with a rule dropped — reads as drift vs canonical."""
    cfg = _canonical("staging_ruleset.json")
    cfg["rules"] = [r for r in cfg["rules"] if r.get("type") != "pull_request"]
    return cfg


def test_from_seed_serves_seeded_rulesets() -> None:
    ruleset = _drifted_staging()
    seed = MockWorldSeed(rulesets={"staging protect": ruleset})

    gh = FakeGitHub.from_seed(seed)

    assert gh.fetch_rulesets("owner/repo") == {"staging protect": ruleset}


def test_fetch_rulesets_empty_by_default() -> None:
    gh = FakeGitHub.from_seed(MockWorldSeed())
    assert gh.fetch_rulesets("owner/repo") == {}


def test_add_ruleset_seed_helper() -> None:
    gh = FakeGitHub()
    gh.add_ruleset("main protect", {"name": "main protect", "enforcement": "active"})

    assert gh.fetch_rulesets("owner/repo") == {
        "main protect": {"name": "main protect", "enforcement": "active"}
    }


def test_fetch_rulesets_returns_copies_not_internal_state() -> None:
    """Mutating the served dict must not corrupt the Fake's seeded state."""
    ruleset = _drifted_staging()
    gh = FakeGitHub.from_seed(MockWorldSeed(rulesets={"staging protect": ruleset}))

    served = gh.fetch_rulesets("owner/repo")
    served["injected"] = {}
    served["staging protect"]["enforcement"] = "disabled"

    assert gh.fetch_rulesets("owner/repo") == {"staging protect": ruleset}


def test_fake_fetcher_injectable_into_audit_repo_reports_drift() -> None:
    """The Fake fetcher plugs into ``audit_repo`` and yields observable drift.

    This is the seam the s41 branch_protection_auditor sandbox scenario needs:
    seed a drifted live ruleset, run the real audit engine against the real
    canonical contract, and get a non-clean report — no network required.
    """
    seed = MockWorldSeed(
        rulesets={
            "main protect": _canonical("main_ruleset.json"),
            "staging protect": _drifted_staging(),
        }
    )
    gh = FakeGitHub.from_seed(seed)

    report = audit_repo("owner/repo", _CANONICAL_DIR, fetch_rulesets=gh.fetch_rulesets)

    assert not report.clean
    assert any("staging protect" in line for line in report.drifts)


def test_fake_fetcher_injectable_into_audit_repo_clean_when_matched() -> None:
    """Seeding the canonical rulesets verbatim yields a clean audit."""
    seed = MockWorldSeed(
        rulesets={
            "main protect": _canonical("main_ruleset.json"),
            "staging protect": _canonical("staging_ruleset.json"),
        }
    )
    gh = FakeGitHub.from_seed(seed)

    report = audit_repo("owner/repo", _CANONICAL_DIR, fetch_rulesets=gh.fetch_rulesets)

    assert report.clean, report.drifts
