"""Scenario: detector-calibration churn mining through MockWorld.

Two closes of the same normalized escalation subject inside the window →
one `detector-calibration` finding via FakeGitHub; churn stops → the
finding auto-closes and detection re-arms.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


class TestDetectorCalibrationScenario:
    async def test_churn_files_then_autocloses(self, tmp_path):
        world = MockWorld(tmp_path)
        gh = world.github

        async def _closed_escalation(title: str, age_days: int) -> int:
            number = await gh.create_issue(title, "body", ["hitl-escalation"])
            await gh.close_issue(number)
            stamp = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
            gh.issue(number).updated_at = stamp
            return number

        churn_1 = await _closed_escalation(
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
            age_days=12,
        )
        churn_2 = await _closed_escalation(
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 6",
            age_days=2,
        )
        # A singleton subject must NOT trip the miner.
        await _closed_escalation(
            "HITL: flaky test tests.a.test_x unresolved after 3 attempts",
            age_days=3,
        )

        stats = (await world.run_with_loops(["detector_calibration"], cycles=1))[
            "detector_calibration"
        ]
        assert stats["filed"] == 1
        findings = await gh.list_issues_by_label("detector-calibration")
        assert len(findings) == 1
        assert "escalation churn" in findings[0]["title"]

        # Churn window clears (both closes age out) → auto-close + re-arm.
        aged = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        gh.issue(churn_1).updated_at = aged
        gh.issue(churn_2).updated_at = aged

        stats2 = (await world.run_with_loops(["detector_calibration"], cycles=1))[
            "detector_calibration"
        ]
        assert stats2["autoclosed"] == 1
        assert await gh.list_issues_by_label("detector-calibration") == []
