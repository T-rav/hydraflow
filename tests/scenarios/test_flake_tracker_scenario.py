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
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=101)

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
            pr_manager=fake_pr,
            flake_fetch_runs=fake_fetch,
            flake_download_junit=fake_download,
            flake_reconcile_closed=fake_reconcile,
        )

        await world.run_with_loops(["flake_tracker"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        args = fake_pr.create_issue.await_args.args
        title, _body, labels = args[0], args[1], args[2]
        assert "test_flaky" in title
        assert "flake rate: 4/20" in title
        assert "flaky-test" in labels
        assert "hydraflow-find" in labels
        fake_fetch.assert_awaited_once()
        # _download_junit called once per run
        assert fake_download.await_count == 20
        fake_reconcile.assert_awaited_once()

    async def test_no_file_below_threshold(self, tmp_path) -> None:
        """20 RC runs with 2 failures (< threshold=3) → no issue filed."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

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
            pr_manager=fake_pr,
            flake_fetch_runs=AsyncMock(return_value=fake_runs),
            flake_download_junit=AsyncMock(
                side_effect=lambda r: make_run_results(r["databaseId"])
            ),
            flake_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["flake_tracker"], cycles=1)
        assert fake_pr.create_issue.await_count == 0
