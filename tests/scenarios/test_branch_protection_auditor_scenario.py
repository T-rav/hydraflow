"""MockWorld scenario for BranchProtectionAuditorLoop (ADR-0082).

Drives the loop end-to-end through the catalog with a seeded auditor (no gh):
ruleset drift files exactly one branch-protection-drift issue; a clean audit
files none.

``TestUndeclaredLegacyLayerDrift`` (#10148) goes one layer deeper: instead of
injecting a canned ``AuditReport``, it wires the loop's ``branch_protection_
audit`` port to the REAL ``audit_repo`` diff engine running against
``FakeGitHub``'s ``fetch_rulesets``/``fetch_legacy_protection`` seams and the
repo's real declarative contract (``docs/standards/branch_protection``) — so
the loop-level assertion (drift => exactly one filed issue; clean => none)
exercises the actual undeclared-legacy-layer comparison logic, not just the
loop's generic drift-to-issue plumbing.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from branch_protection_audit import AuditReport, audit_repo
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

_CANONICAL_DIR = Path("docs/standards/branch_protection")
# The exact undeclared-legacy-layer drift from #10148: a legacy
# branch-protection rule on staging requires 5 contexts gates.toml declares
# required_on ["main"] only (signal-only on staging per ADR-0042).
_LEGACY_LAYER_CONTEXTS = [
    "Tests",
    "Type Check",
    "quality (.)",
    "Architecture Check",
    "Lint & Format",
]


def _canonical(name: str) -> dict:
    return json.loads((_CANONICAL_DIR / name).read_text())


class TestBranchProtectionAuditor:
    async def test_drift_files_one_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(
            return_value=AuditReport(
                repo="o/r",
                drifts=["[main protect] DRIFT: canonical and live differ."],
            )
        )

        _seed_ports(world, branch_protection_audit=auditor)

        await world.run_with_loops(["branch_protection_auditor"], cycles=1)

        issues = await world.github.list_issues_by_label(
            "hydraflow-branch-protection-drift"
        )
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])
        assert "branch-protection" in issue.title
        assert "make gen-gates" in issue.body
        assert "hydraflow-find" in issue.labels
        assert "hydraflow-branch-protection-drift" in issue.labels

    async def test_clean_audit_files_no_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=AuditReport(repo="o/r", drifts=[]))

        _seed_ports(world, branch_protection_audit=auditor)

        await world.run_with_loops(["branch_protection_auditor"], cycles=1)

        assert (
            await world.github.list_issues_by_label("hydraflow-branch-protection-drift")
            == []
        )


class TestUndeclaredLegacyLayerDrift:
    """#10148: the loop, wired to the REAL audit engine, catches an undeclared
    legacy branch-protection layer that a ruleset-only diff cannot see."""

    def _wire_real_auditor(self, world: MockWorld) -> None:
        """Point the loop's audit port at the real ``audit_repo`` running
        against ``world.github`` (the same FakeGitHub the loop's other ports
        share) and the repo's real declarative contract."""

        async def _audit() -> AuditReport:
            return audit_repo(
                "o/r",
                _CANONICAL_DIR,
                fetch_rulesets=world.github.fetch_rulesets,
                fetch_legacy_protection=world.github.fetch_legacy_protection,
            )

        _seed_ports(world, branch_protection_audit=_audit)

    async def test_legacy_layer_on_staging_files_one_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        # Live rulesets match canonical exactly — zero ruleset drift.
        world.github.add_ruleset("main protect", _canonical("main_ruleset.json"))
        world.github.add_ruleset("staging protect", _canonical("staging_ruleset.json"))
        # But a legacy branch-protection rule on staging additionally requires
        # 5 main-only contexts — the undeclared layer this PR detects.
        world.github.add_legacy_protection(
            "staging",
            {"required_status_checks": {"contexts": _LEGACY_LAYER_CONTEXTS}},
        )
        self._wire_real_auditor(world)

        await world.run_with_loops(["branch_protection_auditor"], cycles=1)

        issues = await world.github.list_issues_by_label(
            "hydraflow-branch-protection-drift"
        )
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])
        for ctx in _LEGACY_LAYER_CONTEXTS:
            assert ctx in issue.body

    async def test_no_legacy_layer_files_no_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        # Live rulesets match canonical exactly and no classic protection is
        # seeded at all — fully clean.
        world.github.add_ruleset("main protect", _canonical("main_ruleset.json"))
        world.github.add_ruleset("staging protect", _canonical("staging_ruleset.json"))
        self._wire_real_auditor(world)

        await world.run_with_loops(["branch_protection_auditor"], cycles=1)

        assert (
            await world.github.list_issues_by_label("hydraflow-branch-protection-drift")
            == []
        )
