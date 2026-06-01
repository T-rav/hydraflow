"""MockWorld scenario for LabelDriftWatcherLoop.

This verifies the catalog entry is not just instantiable: the real loop runs
through MockWorld, detects label drift using FakeGitHub, reconciles labels, and
records the expected audit comment.
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


class TestLabelDriftWatcherLoopScenario:
    """LabelDriftWatcherLoop reconciles issue/PR label drift in MockWorld."""

    async def test_pr_ahead_of_issue_is_reconciled(self, tmp_path):
        world = MockWorld(tmp_path)
        world.github.add_issue(
            42,
            "Feature work",
            "Issue is still ready while the PR is in review.",
            labels=["hydraflow-ready"],
        )
        world.github.add_pr(number=100, issue_number=42, branch="hf/issue-42")
        world.github.add_pr_label(100, "hydraflow-review")

        stats = await world.run_with_loops(["label_drift_watcher"], cycles=1)

        assert stats["label_drift_watcher"] == {"detected": 1, "reconciled": 1}
        issue = world.github.issue(42)
        assert "hydraflow-review" in issue.labels
        assert "hydraflow-ready" not in issue.labels
        assert len(issue.comments) == 1
        assert "LabelDriftWatcher" in issue.comments[0]
