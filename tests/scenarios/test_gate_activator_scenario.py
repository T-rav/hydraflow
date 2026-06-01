"""MockWorld scenario for GateActivatorLoop (ADR-0082, Slice 4).

Drives the loop end-to-end through the catalog with a seeded detector (no file
IO): a planned gate whose surface exists files exactly one gate-activation
issue; an empty detection files none.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from scripts.gates.activation import ActivationProposal

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

_PROPOSAL = ActivationProposal(
    name="Browser Scenarios",
    dimension="browser-e2e",
    required_on=("main",),
    workflow="ci.yml",
    job="browser",
    make_target="test-browser",
)


class TestGateActivator:
    async def test_proposals_file_one_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        detector = AsyncMock(return_value=[_PROPOSAL])

        _seed_ports(world, gate_activation_detect=detector)

        await world.run_with_loops(["gate_activator"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-gate-activation")
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])
        assert "gate-activation" in issue.title
        assert "Browser Scenarios" in issue.body
        assert "make gen-gates" in issue.body
        assert "hydraflow-find" in issue.labels
        assert "hydraflow-gate-activation" in issue.labels

    async def test_no_proposals_files_no_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        detector = AsyncMock(return_value=[])

        _seed_ports(world, gate_activation_detect=detector)

        await world.run_with_loops(["gate_activator"], cycles=1)

        assert (
            await world.github.list_issues_by_label("hydraflow-gate-activation") == []
        )
