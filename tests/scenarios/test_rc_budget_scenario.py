"""MockWorld scenario for RCBudgetLoop (spec §4.8).

Two scenarios over a 30-day synthetic RC-promotion history:

* ``test_files_issue_on_spike`` — 29 prior runs at ~300s + a current run at
  900s (spike_ratio=2.0 → fires at 640s). RCBudgetLoop must file at least
  one ``hydraflow-find`` + ``rc-duration-regression`` issue.
* ``test_no_file_when_within_budget`` — 29 prior runs at ~300s + a current
  run also at 300s. Neither signal trips; no issue filed.

The loop's external ``gh`` subprocess surface (``_fetch_recent_runs`` /
``_fetch_job_breakdown`` / ``_fetch_junit_tests`` /
``_reconcile_closed_escalations``) is stubbed via pre-seeded port keys
which the catalog builder in ``loop_registrations.py`` reads and
monkey-patches onto the instance — mirrors the F7 FlakeTracker
(``eac5fc72``), S6 SkillPromptEval (``93ebf387``), and C6
FakeCoverageAuditor (``32b43ab0``) patterns.
"""

from __future__ import annotations

import datetime as _dt
from unittest.mock import AsyncMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _make_runs(current_duration_s: int) -> list[dict[str, str | int]]:
    """Build a synthetic 30d history: 29 prior @ 300s + current @ N seconds."""
    now = _dt.datetime(2026, 4, 22, 12, 0, 0, tzinfo=_dt.UTC)
    runs: list[dict[str, str | int]] = []
    for i in range(29, 0, -1):
        started = now - _dt.timedelta(days=i)
        runs.append(
            {
                "databaseId": 1000 + i,
                "url": f"https://example/run/{1000 + i}",
                "conclusion": "success",
                "createdAt": started.isoformat().replace("+00:00", "Z"),
                "duration_s": 300,
            }
        )
    runs.append(
        {
            "databaseId": 2000,
            "url": "https://example/run/2000",
            "conclusion": "success",
            "createdAt": now.isoformat().replace("+00:00", "Z"),
            "duration_s": current_duration_s,
        }
    )
    runs.sort(key=lambda r: str(r["createdAt"]), reverse=True)
    return runs


class TestRCBudgetScenario:
    """§4.8 — RC wall-clock regression MockWorld scenarios."""

    async def test_files_issue_on_spike(self, tmp_path) -> None:
        """Current run at 900s vs ~300s history → spike signal fires."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=4242)

        runs = _make_runs(current_duration_s=900)

        _seed_ports(
            world,
            pr_manager=fake_pr,
            rc_budget_fetch_runs=AsyncMock(return_value=runs),
            rc_budget_fetch_jobs=AsyncMock(return_value=[]),
            rc_budget_fetch_junit=AsyncMock(return_value=[]),
            rc_budget_reconcile_closed=AsyncMock(return_value=None),
        )

        stats = await world.run_with_loops(["rc_budget"], cycles=1)

        assert stats["rc_budget"]["status"] == "ok", stats
        assert stats["rc_budget"]["filed"] >= 1, stats
        assert fake_pr.create_issue.await_count >= 1
        title = fake_pr.create_issue.await_args.args[0]
        labels = fake_pr.create_issue.await_args.args[2]
        assert "RC gate duration regression" in title
        assert "hydraflow-find" in labels
        assert "rc-duration-regression" in labels

    async def test_no_file_when_within_budget(self, tmp_path) -> None:
        """Current run matches history baseline → no signal, no file."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

        runs = _make_runs(current_duration_s=300)

        _seed_ports(
            world,
            pr_manager=fake_pr,
            rc_budget_fetch_runs=AsyncMock(return_value=runs),
            rc_budget_fetch_jobs=AsyncMock(return_value=[]),
            rc_budget_fetch_junit=AsyncMock(return_value=[]),
            rc_budget_reconcile_closed=AsyncMock(return_value=None),
        )

        stats = await world.run_with_loops(["rc_budget"], cycles=1)

        assert stats["rc_budget"]["status"] == "ok", stats
        assert stats["rc_budget"]["filed"] == 0, stats
        assert stats["rc_budget"]["escalated"] == 0, stats
        fake_pr.create_issue.assert_not_awaited()
