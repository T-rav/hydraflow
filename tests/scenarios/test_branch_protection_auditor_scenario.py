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
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=5001)
        auditor = AsyncMock(
            return_value=AuditReport(
                repo="o/r",
                drifts=["[main protect] DRIFT: canonical and live differ."],
            )
        )

        _seed_ports(world, pr_manager=fake_pr, branch_protection_audit=auditor)

        await world.run_with_loops(["branch_protection_auditor"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        title, body = fake_pr.create_issue.await_args.args[:2]
        labels = fake_pr.create_issue.await_args.kwargs.get("labels", [])
        assert "branch-protection" in title
        assert "make gen-gates" in body
        assert "hydraflow-find" in labels
        assert "hydraflow-branch-protection-drift" in labels

    async def test_clean_audit_files_no_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=5002)
        auditor = AsyncMock(return_value=AuditReport(repo="o/r", drifts=[]))

        _seed_ports(world, pr_manager=fake_pr, branch_protection_audit=auditor)

        await world.run_with_loops(["branch_protection_auditor"], cycles=1)

        fake_pr.create_issue.assert_not_awaited()
