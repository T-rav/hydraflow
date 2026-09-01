"""MockWorld: the caretaker files when a repo's charter loses its purpose.

Unit tests see the findings `compute_charter_drift` returns. Only this layer
sees whether a NEW fatal finding class actually reaches an operator — the
caretaker groups by finding class and dedups per repo, so a class that nothing
routes would produce findings no one is told about (#11856).

That is the specific risk here: `missing-purpose` was added to the drift
computation, not to the caretaker, on the theory that the caretaker iterates
classes generically. This proves the theory rather than assuming it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from charter import (
    FINDING_MISSING_PURPOSE,
    FINDING_UNKNOWN_STANDARD,
    CharterDriftReport,
    CharterFinding,
)
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

_NO_PURPOSE = CharterDriftReport(
    repo="o/r",
    findings=(
        CharterFinding(
            check_id=f"{FINDING_MISSING_PURPOSE}:product",
            finding_class=FINDING_MISSING_PURPOSE,
            detail="`charter.yaml` states no `purpose.product`",
        ),
        CharterFinding(
            check_id=f"{FINDING_MISSING_PURPOSE}:goals",
            finding_class=FINDING_MISSING_PURPOSE,
            detail="`charter.yaml` names no `purpose.goals`",
        ),
    ),
)

_STATED_PURPOSE = CharterDriftReport(
    repo="o/r",
    findings=(
        CharterFinding(
            check_id=f"{FINDING_UNKNOWN_STANDARD}:soc2_ready",
            finding_class=FINDING_UNKNOWN_STANDARD,
            detail="neither carried nor shipped",
        ),
    ),
)


class TestPurposeDrift:
    async def test_a_charter_that_lost_its_purpose_files_one_issue(
        self, tmp_path
    ) -> None:
        world = MockWorld(tmp_path)
        _seed_ports(world, charter_drift_audit=AsyncMock(return_value=[_NO_PURPOSE]))

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        assert len(issues) == 1

    async def test_the_issue_names_both_halves(self, tmp_path) -> None:
        # One issue per finding CLASS, but it must carry every check_id in the
        # class or the operator learns that purpose is wrong without learning
        # which half.
        world = MockWorld(tmp_path)
        _seed_ports(world, charter_drift_audit=AsyncMock(return_value=[_NO_PURPOSE]))

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        body = world.github.issue(issues[0]["number"]).body
        assert f"{FINDING_MISSING_PURPOSE}:product" in body
        assert f"{FINDING_MISSING_PURPOSE}:goals" in body

    async def test_a_stated_purpose_files_nothing(self, tmp_path) -> None:
        # The decoy. A caretaker that filed on every report would pass the two
        # tests above while saying nothing about `missing-purpose` at all.
        world = MockWorld(tmp_path)
        _seed_ports(
            world, charter_drift_audit=AsyncMock(return_value=[_STATED_PURPOSE])
        )

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        assert issues == []

    async def test_a_second_tick_does_not_file_again(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        _seed_ports(world, charter_drift_audit=AsyncMock(return_value=[_NO_PURPOSE]))

        await world.run_with_loops(["charter_drift_caretaker"], cycles=2)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        assert len(issues) == 1


class TestTheActuatorIsWiredInMockWorld:
    """#11856 — the collaborator has to reach the loop, not just exist.

    `test_collaborator_wiring` caught this: `purpose_auditor` was forwarded at
    the production composition root and NOT in the scenario catalog builder, so
    every scenario would have run the loop with the actuator absent and its
    tests would have passed on a loop that could not file anything.

    Seeded through `charter_purpose_audit`, which is the seam a scenario uses
    to say what the seam decided.
    """

    async def test_an_unanchored_goal_files_an_issue_through_the_loop(
        self, tmp_path
    ) -> None:
        from policy.models import DecisionStatus, StandardDecision

        world = MockWorld(tmp_path)
        _seed_ports(
            world,
            charter_drift_audit=AsyncMock(return_value=[]),
            charter_purpose_audit=AsyncMock(
                return_value=[
                    StandardDecision(
                        standard="purpose",
                        subject="a_goal",
                        status=DecisionStatus.VIOLATED,
                        blocking=False,
                        reason="cited by nothing",
                    )
                ]
            ),
        )

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-charter-drift")
        assert len(issues) == 1
        assert "a_goal" in world.github.issue(issues[0]["number"]).title

    async def test_a_compliant_goal_files_nothing(self, tmp_path) -> None:
        # The decoy: a loop that filed on every decision would open an issue
        # for every goal that IS cited.
        from policy.models import DecisionStatus, StandardDecision

        world = MockWorld(tmp_path)
        _seed_ports(
            world,
            charter_drift_audit=AsyncMock(return_value=[]),
            charter_purpose_audit=AsyncMock(
                return_value=[
                    StandardDecision(
                        standard="purpose",
                        subject="a_goal",
                        status=DecisionStatus.COMPLIANT,
                        blocking=False,
                        reason="cited",
                    )
                ]
            ),
        )

        await world.run_with_loops(["charter_drift_caretaker"], cycles=1)

        assert await world.github.list_issues_by_label("hydraflow-charter-drift") == []
