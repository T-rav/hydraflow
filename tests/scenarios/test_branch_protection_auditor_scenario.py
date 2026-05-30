"""MockWorld scenario for BranchProtectionAuditorLoop (ADR-0082).

Drives the loop end-to-end through the catalog with a seeded auditor (no gh):
ruleset drift files exactly one branch-protection-drift issue; a clean audit
files none.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from branch_protection_audit import AuditReport
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


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
