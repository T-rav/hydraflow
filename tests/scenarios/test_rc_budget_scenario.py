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

        runs = _make_runs(current_duration_s=900)

        _seed_ports(
            world,
            rc_budget_fetch_runs=AsyncMock(return_value=runs),
            rc_budget_fetch_jobs=AsyncMock(return_value=[]),
            rc_budget_fetch_junit=AsyncMock(return_value=[]),
            rc_budget_reconcile_closed=AsyncMock(return_value=None),
        )

        stats = await world.run_with_loops(["rc_budget"], cycles=1)

        assert stats["rc_budget"]["status"] == "ok", stats
        assert stats["rc_budget"]["filed"] >= 1, stats
        issues = await world.github.list_issues_by_label("rc-duration-regression")
        assert len(issues) >= 1
        issue = world.github.issue(issues[0]["number"])
        assert "RC gate duration regression" in issue.title
        assert "hydraflow-find" in issue.labels
        assert "rc-duration-regression" in issue.labels

    async def test_no_file_when_within_budget(self, tmp_path) -> None:
        """Current run matches history baseline → no signal, no file."""
        world = MockWorld(tmp_path)

        runs = _make_runs(current_duration_s=300)

        _seed_ports(
            world,
            rc_budget_fetch_runs=AsyncMock(return_value=runs),
            rc_budget_fetch_jobs=AsyncMock(return_value=[]),
            rc_budget_fetch_junit=AsyncMock(return_value=[]),
            rc_budget_reconcile_closed=AsyncMock(return_value=None),
        )

        stats = await world.run_with_loops(["rc_budget"], cycles=1)

        assert stats["rc_budget"]["status"] == "ok", stats
        assert stats["rc_budget"]["filed"] == 0, stats
        assert stats["rc_budget"]["escalated"] == 0, stats
        assert await world.github.list_issues_by_label("rc-duration-regression") == []

    async def test_cancelled_current_run_is_excluded_from_duration_analysis(
        self, tmp_path
    ) -> None:
        """#10215 — a job-timeout-cancelled run must never be misread as a
        wall-clock regression.

        Unlike the two scenarios above, ``rc_budget_fetch_runs`` is left
        UNSEEDED so the loop's real ``_fetch_recent_runs`` runs against a
        real ``GitHubDataCache`` + ``FakeGitHub`` (seeded via
        ``add_workflow_run``) — the only way to exercise the cancelled-run
        filter itself rather than a pre-filtered fixture. 6 healthy runs
        at 300s plus a newest run CANCELLED after ~2715s (a GH Actions
        timeout kill, mirroring the real incident) must be excluded
        entirely: it may not become "current", it may not pollute the
        baseline, and ``runs_seen`` must reflect only the 6 real runs.
        """
        from github_cache_loop import RC_PROMOTION_WORKFLOW

        # Seed the display name in ``workflow`` and the file the loop queries by
        # in ``workflow_file`` — FakeGitHub keys list_runs_for_workflow on the
        # file and projects the display name in list_workflow_runs (#10911).
        rc_promotion_name = "RC Promotion Scenario"  # rc-promotion-scenario.yml .name
        world = MockWorld(tmp_path)

        now = _dt.datetime.now(_dt.UTC)
        for i in range(6, 0, -1):
            started = now - _dt.timedelta(days=i)
            completed = started + _dt.timedelta(seconds=300)
            world.github.add_workflow_run(
                3000 + i,
                workflow=rc_promotion_name,
                workflow_file=RC_PROMOTION_WORKFLOW,
                conclusion="success",
                created_at=started.isoformat().replace("+00:00", "Z"),
                run_started_at=started.isoformat().replace("+00:00", "Z"),
                updated_at=completed.isoformat().replace("+00:00", "Z"),
            )

        hang_completed = now + _dt.timedelta(seconds=2715)
        world.github.add_workflow_run(
            4000,
            workflow=rc_promotion_name,
            workflow_file=RC_PROMOTION_WORKFLOW,
            conclusion="cancelled",
            created_at=now.isoformat().replace("+00:00", "Z"),
            run_started_at=now.isoformat().replace("+00:00", "Z"),
            updated_at=hang_completed.isoformat().replace("+00:00", "Z"),
        )

        _seed_ports(
            world,
            rc_budget_fetch_jobs=AsyncMock(return_value=[]),
            rc_budget_fetch_junit=AsyncMock(return_value=[]),
        )

        stats = await world.run_with_loops(["rc_budget"], cycles=1)

        assert stats["rc_budget"]["status"] == "ok", stats
        assert stats["rc_budget"]["runs_seen"] == 6, stats
        assert stats["rc_budget"]["filed"] == 0, stats
        assert await world.github.list_issues_by_label("rc-duration-regression") == []
