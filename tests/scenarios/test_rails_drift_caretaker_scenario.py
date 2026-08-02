"""MockWorld scenario for RailsDriftCaretakerLoop (ADR-0121, #10936).

Drives the loop end-to-end through the LoopCatalog with a seeded auditor (no
filesystem): manifest drift files exactly one rails-drift issue per finding
class; a clean audit files none (idle poll); a manifest declaring only a
future/unknown layer files none (tolerated, not fatal).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rails_manifest import (
    FINDING_MISSING_LAYER,
    FINDING_UNKNOWN_LAYER,
    RailsDriftReport,
    RailsFinding,
)
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

_DRIFT = RailsDriftReport(
    repo="o/r",
    findings=(
        RailsFinding(
            check_id="missing-layer:language_pack",
            finding_class=FINDING_MISSING_LAYER,
            detail="the 'language_pack' layer is gone",
        ),
    ),
)
_UNKNOWN_ONLY = RailsDriftReport(
    repo="o/r",
    findings=(
        RailsFinding(
            check_id="unknown-layer:operator_agent_pack",
            finding_class=FINDING_UNKNOWN_LAYER,
            detail="tolerated future layer",
        ),
    ),
)


class TestRailsDriftCaretaker:
    async def test_drift_files_one_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[_DRIFT])
        _seed_ports(world, rails_drift_audit=auditor)

        await world.run_with_loops(["rails_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-rails-drift")
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])
        assert "rails-drift" in issue.title
        assert "missing-layer:language_pack" in issue.body
        assert "hydraflow-find" in issue.labels
        assert "hydraflow-rails-drift" in issue.labels

    async def test_clean_audit_files_no_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[RailsDriftReport(repo="o/r", findings=())])
        _seed_ports(world, rails_drift_audit=auditor)

        await world.run_with_loops(["rails_drift_caretaker"], cycles=1)

        assert await world.github.list_issues_by_label("hydraflow-rails-drift") == []

    async def test_unknown_layer_only_files_no_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[_UNKNOWN_ONLY])
        _seed_ports(world, rails_drift_audit=auditor)

        await world.run_with_loops(["rails_drift_caretaker"], cycles=1)

        assert await world.github.list_issues_by_label("hydraflow-rails-drift") == []
