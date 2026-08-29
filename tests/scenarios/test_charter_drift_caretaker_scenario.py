"""MockWorld scenario for CharterDriftCaretakerLoop (#11748; ADR-0121, ADR-0143).

Drives the loop end-to-end through the LoopCatalog with a seeded auditor (no
filesystem). Covers the three outcomes the tolerance rules distinguish: a
declared standard that vanished from the tree files exactly one
`missing-standard` issue; a clean audit files none; and a charter whose only
findings are tolerated (an unknown standard id, a future layer name, a legacy
`rails.yaml` fallback) files none either.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from charter import (
    FINDING_LEGACY_RAILS_MANIFEST,
    FINDING_MISSING_ARTIFACT,
    FINDING_MISSING_STANDARD,
    FINDING_UNKNOWN_LAYER,
    FINDING_UNKNOWN_STANDARD,
    CharterDriftReport,
    CharterFinding,
)
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

_MISSING_STANDARD = CharterDriftReport(
    repo="o/r",
    findings=(
        CharterFinding(
            check_id=f"{FINDING_MISSING_STANDARD}:testing",
            finding_class=FINDING_MISSING_STANDARD,
            detail="charter declares 'testing' but docs/standards/testing/ is gone",
        ),
    ),
)
_MISSING_STANDARD_AND_ARTIFACT = CharterDriftReport(
    repo="o/r",
    findings=(
        *_MISSING_STANDARD.findings,
        CharterFinding(
            check_id=f"{FINDING_MISSING_ARTIFACT}:docs/adr",
            finding_class=FINDING_MISSING_ARTIFACT,
            detail="charter declares docs/adr but it is absent",
        ),
    ),
)
_TOLERATED_ONLY = CharterDriftReport(
    repo="o/r",
    findings=(
        CharterFinding(
            check_id=f"{FINDING_UNKNOWN_STANDARD}:soc2_ready",
            finding_class=FINDING_UNKNOWN_STANDARD,
            detail="neither carried nor shipped",
        ),
        CharterFinding(
            check_id=f"{FINDING_UNKNOWN_LAYER}:operator_agent_pack",
            finding_class=FINDING_UNKNOWN_LAYER,
            detail="tolerated future layer",
        ),
        CharterFinding(
            check_id=f"{FINDING_LEGACY_RAILS_MANIFEST}:rails.yaml",
            finding_class=FINDING_LEGACY_RAILS_MANIFEST,
            detail="loaded from a legacy rails.yaml",
        ),
    ),
)


class TestCharterDriftCaretaker:
    async def test_missing_standard_files_one_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[_MISSING_STANDARD])
        _seed_ports(world, charter_drift_audit=auditor)

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        assert len(issues) == 1

    async def test_missing_standard_issue_names_the_standard(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[_MISSING_STANDARD])
        _seed_ports(world, charter_drift_audit=auditor)

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        issue = world.github.issue(issues[0]["number"])
        assert f"{FINDING_MISSING_STANDARD}:testing" in issue.body

    async def test_missing_standard_issue_is_labelled_for_the_finder(
        self, tmp_path
    ) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[_MISSING_STANDARD])
        _seed_ports(world, charter_drift_audit=auditor)

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        assert "hydraflow-find" in world.github.issue(issues[0]["number"]).labels

    async def test_one_issue_per_finding_class(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[_MISSING_STANDARD_AND_ARTIFACT])
        _seed_ports(world, charter_drift_audit=auditor)

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        assert len(issues) == 2

    async def test_repeat_tick_does_not_refile(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[_MISSING_STANDARD])
        _seed_ports(world, charter_drift_audit=auditor)

        await world.run_with_loops(["charter_drift_caretaker"], cycles=2)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        assert len(issues) == 1

    async def test_clean_audit_files_no_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[CharterDriftReport(repo="o/r", findings=())])
        _seed_ports(world, charter_drift_audit=auditor)

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        assert await world.github.list_issues_by_label("hydraflow-charter-drift") == []

    async def test_tolerated_findings_only_file_no_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        auditor = AsyncMock(return_value=[_TOLERATED_ONLY])
        _seed_ports(world, charter_drift_audit=auditor)

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        assert await world.github.list_issues_by_label("hydraflow-charter-drift") == []
