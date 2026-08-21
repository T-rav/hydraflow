"""Scenario: detector-calibration churn mining through MockWorld.

Two closes of the same normalized escalation subject inside the window →
one `detector-calibration` finding via FakeGitHub; churn stops → the
finding auto-closes and detection re-arms.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

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

    async def test_distinct_entities_do_not_fabricate_churn(self, tmp_path):
        """#11405 — three distinct PRs escalating once each is not churn.

        Each closed escalation names a different PR via a ``#N`` reference
        in the title; normalize must keep that identity distinct so three
        one-time escalations don't mine into one fabricated "churn" finding.
        """
        world = MockWorld(tmp_path)
        gh = world.github

        async def _closed_escalation(title: str, age_days: int) -> int:
            number = await gh.create_issue(title, "body", ["hitl-escalation"])
            await gh.close_issue(number)
            stamp = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
            gh.issue(number).updated_at = stamp
            return number

        for pr_number, age_days in ((10817, 20), (11241, 10), (11242, 1)):
            await _closed_escalation(
                f"Sampled re-audit disagreement: PR #{pr_number} (gauntlet) — "
                "adversarial re-review flags a possible silent escape",
                age_days=age_days,
            )

        stats = (await world.run_with_loops(["detector_calibration"], cycles=1))[
            "detector_calibration"
        ]
        assert stats["filed"] == 0
        assert await gh.list_issues_by_label("detector-calibration") == []

    async def test_spray_fires_then_autocloses(self, tmp_path):
        """#11427 — one template fired against many distinct #N entities
        files a spray finding even though no single entity repeats; the
        finding auto-closes once the spray window clears."""
        world = MockWorld(tmp_path)
        gh = world.github

        async def _closed_escalation(title: str, age_days: int) -> int:
            number = await gh.create_issue(title, "body", ["hitl-escalation"])
            await gh.close_issue(number)
            stamp = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
            gh.issue(number).updated_at = stamp
            return number

        spray_entities = [
            await _closed_escalation(
                f"HITL: convergence oscillation detected for #{9001 + i}",
                age_days=i + 1,
            )
            for i in range(5)
        ]

        stats = (await world.run_with_loops(["detector_calibration"], cycles=1))[
            "detector_calibration"
        ]
        assert stats["filed"] == 1
        assert stats["spraying_templates"] == 1
        findings = await gh.list_issues_by_label("detector-calibration")
        assert len(findings) == 1
        assert "escalation spray" in findings[0]["title"]

        # Spray window clears: every entity's close ages out → auto-close.
        aged = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        for number in spray_entities:
            gh.issue(number).updated_at = aged

        stats2 = (await world.run_with_loops(["detector_calibration"], cycles=1))[
            "detector_calibration"
        ]
        assert stats2["autoclosed"] == 1
        assert await gh.list_issues_by_label("detector-calibration") == []

    async def test_scans_served_from_cache_without_subprocess(
        self, tmp_path, monkeypatch
    ) -> None:
        """#9814 — closed-escalation scan flows loop → GitHubDataCache → fake port.

        A poisoned ``create_subprocess_exec`` proves no raw ``gh issue
        list`` fires on the tick; the churn finding still lands.
        """
        import asyncio

        world = MockWorld(tmp_path)
        gh = world.github

        for suffix in ("after 3", "after 6"):
            number = await gh.create_issue(
                f"HITL: fake coverage gap X unresolved {suffix}",
                "body",
                ["hitl-escalation"],
            )
            await gh.close_issue(number)
            gh.issue(number).updated_at = (
                datetime.now(UTC) - timedelta(days=2)
            ).isoformat()

        def _no_subprocess(*_a, **_k):
            raise AssertionError("raw gh subprocess fired for a cached issue read")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_subprocess)

        stats = (await world.run_with_loops(["detector_calibration"], cycles=1))[
            "detector_calibration"
        ]

        assert stats["filed"] == 1
        findings = await gh.list_issues_by_label("detector-calibration")
        assert len(findings) == 1

    async def test_gh_down_serves_stale_cache_without_loop_crash(
        self, tmp_path, caplog
    ) -> None:
        """#9814 — a full gh outage degrades to the stale snapshot, never a crash.

        Tick 1 (healthy) warms the shared cache and files the churn
        finding. The cache snapshot is then backdated past its TTL (but
        inside the 3x stale-serve grace) and FakeGitHub's rate-limit mode
        poisons EVERY port call. Tick 2 must complete: the closed scan is
        served stale (with a staleness log line), nothing is re-filed
        (dedup), nothing is spuriously auto-closed, and no exception
        escapes the tick.
        """
        from datetime import timedelta as _td

        from github_cache_loop import CacheSnapshot, GitHubDataCache
        from tests.helpers import ConfigFactory
        from tests.scenarios.helpers.loop_port_seeding import seed_ports

        world = MockWorld(tmp_path)
        gh = world.github

        for suffix in ("after 3", "after 6"):
            number = await gh.create_issue(
                f"HITL: fake coverage gap X unresolved {suffix}",
                "body",
                ["hitl-escalation"],
            )
            await gh.close_issue(number)
            gh.issue(number).updated_at = (
                datetime.now(UTC) - timedelta(days=2)
            ).isoformat()

        cache_cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            github_cache_issue_list_ttl_s=900,
        )
        cache = GitHubDataCache(cache_cfg, gh, MagicMock())
        seed_ports(world, github_cache=cache)

        stats1 = (await world.run_with_loops(["detector_calibration"], cycles=1))[
            "detector_calibration"
        ]
        assert stats1["filed"] == 1

        # Expire the closed-scan snapshot past its bound but inside the
        # 3x grace, then take gh fully down.
        key = "closed:hitl-escalation:500"
        snap = cache._issue_lists[key]
        cache._issue_lists[key] = CacheSnapshot(
            data=snap.data,
            fetched_at=datetime.now(UTC) - _td(seconds=1200),
        )
        gh.set_rate_limit_mode(remaining=0)

        with caplog.at_level("WARNING", logger="hydraflow.github_cache"):
            stats2 = (await world.run_with_loops(["detector_calibration"], cycles=1))[
                "detector_calibration"
            ]

        assert stats2["closed_scanned"] == 2  # stale rows, not []
        assert stats2["filed"] == 0
        assert stats2["autoclosed"] == 0
        assert any("serving stale snapshot" in r.message for r in caplog.records)
        gh.clear_rate_limit()
        assert len(await gh.list_issues_by_label("detector-calibration")) == 1
