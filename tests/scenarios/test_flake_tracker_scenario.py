"""MockWorld scenario for FlakeTrackerLoop (spec §4.5).

Two scenarios over a 20-RC-run window:

* ``test_files_issue_when_threshold_crossed`` — a single test fails on 4 of
  the 20 simulated RC promotion runs (above the default threshold of 3).
  FlakeTrackerLoop must file exactly one ``flaky-test`` +
  ``hydraflow-find`` issue.
* ``test_no_file_below_threshold`` — a test fails on only 2 runs (below
  threshold). The loop must NOT file an issue.

The loop's external subprocess calls (``gh run list`` / ``gh run
download``) and the closed-escalation reconciliation are stubbed by the
scenario via pre-seeded port keys (``flake_fetch_runs``,
``flake_download_junit``, ``flake_reconcile_closed``) which the catalog
builder in ``loop_registrations.py`` reads and monkey-patches onto the
instantiated loop.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestFlakeTracker:
    """§4.5 — flake detector MockWorld scenarios."""

    async def test_files_issue_when_threshold_crossed(self, tmp_path) -> None:
        """20 RC runs with one test failing on 4 → one flaky-test issue filed."""
        world = MockWorld(tmp_path)

        # 20 runs; test_flaky fails on runs 0, 3, 7, 14 → flake count = 4.
        def make_run_results(i: int) -> dict[str, str]:
            bad = i in {0, 3, 7, 14}
            return {
                "tests.scenarios.test_flaky": "fail" if bad else "pass",
                "tests.scenarios.test_alpha": "pass",
            }

        fake_runs = [
            {
                "databaseId": i,
                "url": f"https://example/run/{i}",
                "createdAt": f"2026-04-{i + 1:02d}T00:00:00Z",
            }
            for i in range(20)
        ]
        fake_fetch = AsyncMock(return_value=fake_runs)
        fake_download = AsyncMock(
            side_effect=lambda run: make_run_results(run["databaseId"])
        )
        fake_reconcile = AsyncMock(return_value=None)

        _seed_ports(
            world,
            flake_fetch_runs=fake_fetch,
            flake_download_junit=fake_download,
            flake_reconcile_closed=fake_reconcile,
        )

        await world.run_with_loops(["flake_tracker"], cycles=1)

        issues = await world.github.list_issues_by_label("flaky-test")
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])
        assert "test_flaky" in issue.title
        # Title is stable (#9359); the flake rate moved to the body so the
        # recovery path can find-and-close the issue by exact title.
        assert "flake rate" not in issue.title
        assert "4 of the last 20" in issue.body
        assert "flaky-test" in issue.labels
        assert "hydraflow-find" in issue.labels
        fake_fetch.assert_awaited_once()
        # _download_junit called once per run
        assert fake_download.await_count == 20
        fake_reconcile.assert_awaited_once()

    async def test_no_file_below_threshold(self, tmp_path) -> None:
        """20 RC runs with 2 failures (< threshold=3) → no issue filed."""
        world = MockWorld(tmp_path)

        # Only 2 fails — below default threshold 3.
        def make_run_results(i: int) -> dict[str, str]:
            return {
                "tests.scenarios.test_slow": "fail" if i in {2, 9} else "pass",
                "tests.scenarios.test_alpha": "pass",
            }

        fake_runs = [
            {"databaseId": i, "url": f"https://example/run/{i}"} for i in range(20)
        ]

        _seed_ports(
            world,
            flake_fetch_runs=AsyncMock(return_value=fake_runs),
            flake_download_junit=AsyncMock(
                side_effect=lambda r: make_run_results(r["databaseId"])
            ),
            flake_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["flake_tracker"], cycles=1)
        assert await world.github.list_issues_by_label("flaky-test") == []

    async def test_run_reads_served_from_cache_without_subprocess(
        self, tmp_path, monkeypatch
    ) -> None:
        """#9814 — unseeded run fetch flows loop → GitHubDataCache → fake port.

        ``flake_fetch_runs`` is deliberately NOT seeded: the loop's real
        ``_fetch_recent_runs`` must serve the run window from the shared
        cache (backed by FakeGitHub's ``list_runs_for_workflow``) while a
        poisoned ``create_subprocess_exec`` proves no raw ``gh run list``
        fires on the tick.
        """
        import asyncio

        from github_cache_loop import RC_PROMOTION_WORKFLOW

        world = MockWorld(tmp_path)
        for i in range(20):
            world.github.add_workflow_run(
                i,
                workflow=RC_PROMOTION_WORKFLOW,
                conclusion="success",
                created_at=f"2026-04-{i + 1:02d}T00:00:00Z",
                url=f"https://example/run/{i}",
            )

        def make_run_results(i: int) -> dict[str, str]:
            bad = i in {1, 5, 8, 12}
            return {"tests.scenarios.test_cached": "fail" if bad else "pass"}

        _seed_ports(
            world,
            flake_download_junit=AsyncMock(
                side_effect=lambda run: make_run_results(run["databaseId"])
            ),
            flake_reconcile_closed=AsyncMock(return_value=None),
        )

        def _no_subprocess(*_a, **_k):
            raise AssertionError("raw gh subprocess fired for a cached run read")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_subprocess)

        await world.run_with_loops(["flake_tracker"], cycles=1)

        issues = await world.github.list_issues_by_label("flaky-test")
        assert len(issues) == 1
        assert "test_cached" in world.github.issue(issues[0]["number"]).title
