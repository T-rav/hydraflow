"""Anti-cycle scenario (ADR-0084, pillar C).

An issue that has been escalated out of the pipeline with ``human-required``
must NOT be re-pulled by a core phase — otherwise it re-fails and re-escalates
forever. A clean sibling on the same entry label must still flow to done, so
the guard is specific to the blocker and not a general stall.
"""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestHumanRequiredNotRecycled:
    async def test_human_required_issue_is_not_processed(self, mock_world) -> None:
        world = mock_world
        # Clean control + a human-required sibling, same entry label.
        IssueBuilder().numbered(1).titled("Clean issue").bodied("flows normally").at(
            world
        )
        IssueBuilder().numbered(2).titled("Blocked issue").bodied(
            "escalated to a human"
        ).labeled("hydraflow-find", "human-required").at(world)

        result = await world.run_pipeline()

        clean = result.issue(1)
        assert clean.final_stage == "done"
        assert clean.merged is True

        blocked = result.issue(2)
        assert blocked.final_stage != "done", "human-required issue must not complete"
        assert blocked.merged is False
        assert blocked.plan_result is None, "no phase should have picked it up"
        assert "human-required" in blocked.labels, "blocker must remain until cleared"
