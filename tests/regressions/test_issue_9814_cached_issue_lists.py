"""#9814 — shared cached issue-list-by-label reads in GitHubDataCache.

``triage_retry`` and ``detector_calibration`` used to fire their own
``gh issue list`` subprocess every tick, so gh outages hit every loop at
once and a restart fired every loop's reads simultaneously. The reads now
flow through ``GitHubDataCache.get_issues_by_label``: demand-refreshed,
single-flight, staleness-bounded, degrade-to-stale-then-empty — never a
loop crash.

Pins:
- TTL / refresh / single-flight / stale-serve / empty-degrade semantics.
- Billing signals always propagate (never eaten by the degrade path).
- Disk persistence restores snapshots for restart recovery.
- Detector calibration NEVER auto-closes findings off a degraded empty
  scan (the spurious-close-during-outage failure mode).
- Triage retry ticks complete (scanned=0) when gh is down cold.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from events import EventBus
from github_cache_loop import CacheSnapshot, GitHubDataCache
from subprocess_util import CreditExhaustedError

pytestmark = pytest.mark.asyncio

_TTL = 900.0


def _rows(*numbers: int) -> list[dict]:
    return [
        {"number": n, "title": f"issue {n}", "body": "", "updated_at": ""}
        for n in numbers
    ]


def _cache(tmp_path: Path, pr: AsyncMock, *, ttl: float = _TTL) -> GitHubDataCache:
    from tests.helpers import ConfigFactory

    cfg = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        github_cache_issue_list_ttl_s=ttl,
    )
    return GitHubDataCache(cfg, pr, MagicMock(), cache_dir=tmp_path / "gh_cache")


def _pr(open_rows: list | None = None, closed_rows: list | None = None) -> AsyncMock:
    pr = AsyncMock()
    pr.list_issues_by_label = AsyncMock(return_value=open_rows or [])
    pr.list_closed_issues_by_label = AsyncMock(return_value=closed_rows or [])
    return pr


class TestCachedIssueLists:
    async def test_fresh_snapshot_serves_without_port_call(self, tmp_path) -> None:
        pr = _pr(open_rows=_rows(1, 2))
        cache = _cache(tmp_path, pr)

        first = await cache.get_issues_by_label("parked")
        second = await cache.get_issues_by_label("parked")

        assert first == second == _rows(1, 2)
        pr.list_issues_by_label.assert_awaited_once_with("parked")

    async def test_distinct_keys_fetch_independently(self, tmp_path) -> None:
        pr = _pr(open_rows=_rows(1), closed_rows=_rows(9))
        cache = _cache(tmp_path, pr)

        assert await cache.get_issues_by_label("a") == _rows(1)
        assert await cache.get_issues_by_label("b") == _rows(1)
        closed = await cache.get_issues_by_label("a", state="closed", limit=500)
        assert closed == _rows(9)

        assert pr.list_issues_by_label.await_count == 2
        pr.list_closed_issues_by_label.assert_awaited_once_with("a", limit=500)

    async def test_ttl_zero_always_refreshes(self, tmp_path) -> None:
        pr = _pr(open_rows=_rows(1))
        cache = _cache(tmp_path, pr, ttl=0.0)

        await cache.get_issues_by_label("parked")
        pr.list_issues_by_label.return_value = _rows(1, 2)
        assert await cache.get_issues_by_label("parked") == _rows(1, 2)
        assert pr.list_issues_by_label.await_count == 2

    async def test_concurrent_first_reads_coalesce_single_flight(
        self, tmp_path
    ) -> None:
        """A restart thundering-herd costs one gh call, not one per loop."""
        pr = _pr(open_rows=_rows(1))
        cache = _cache(tmp_path, pr)

        results = await asyncio.gather(
            *(cache.get_issues_by_label("parked") for _ in range(5))
        )

        assert all(r == _rows(1) for r in results)
        pr.list_issues_by_label.assert_awaited_once()

    async def test_refresh_failure_serves_stale_within_grace(
        self, tmp_path, caplog
    ) -> None:
        pr = _pr(open_rows=_rows(1, 2))
        cache = _cache(tmp_path, pr)
        await cache.get_issues_by_label("parked")

        # Expired past the bound but inside the 3x stale-serve grace.
        key = "open:parked:100"
        cache._issue_lists[key] = CacheSnapshot(
            data=_rows(1, 2),
            fetched_at=datetime.now(UTC) - timedelta(seconds=_TTL + 60),
        )
        pr.list_issues_by_label.side_effect = RuntimeError("gh down")

        with caplog.at_level("WARNING", logger="hydraflow.github_cache"):
            rows = await cache.get_issues_by_label("parked")

        assert rows == _rows(1, 2)
        assert any("serving stale snapshot" in r.message for r in caplog.records)

    async def test_refresh_failure_beyond_grace_returns_empty(self, tmp_path) -> None:
        pr = _pr(open_rows=_rows(1))
        cache = _cache(tmp_path, pr)
        await cache.get_issues_by_label("parked")

        key = "open:parked:100"
        cache._issue_lists[key] = CacheSnapshot(
            data=_rows(1),
            fetched_at=datetime.now(UTC) - timedelta(seconds=_TTL * 3 + 60),
        )
        pr.list_issues_by_label.side_effect = RuntimeError("gh down")

        assert await cache.get_issues_by_label("parked") == []

    async def test_refresh_failure_without_snapshot_returns_empty(
        self, tmp_path
    ) -> None:
        pr = _pr()
        pr.list_issues_by_label.side_effect = RuntimeError("gh down")
        cache = _cache(tmp_path, pr)

        assert await cache.get_issues_by_label("parked") == []

    async def test_credit_exhaustion_propagates(self, tmp_path) -> None:
        """Billing signals must never be eaten by the degrade path."""
        pr = _pr()
        pr.list_issues_by_label.side_effect = CreditExhaustedError("credits")
        cache = _cache(tmp_path, pr)

        with pytest.raises(CreditExhaustedError):
            await cache.get_issues_by_label("parked")

    async def test_disk_roundtrip_restores_snapshots(self, tmp_path) -> None:
        pr = _pr(open_rows=_rows(1, 2))
        cache = _cache(tmp_path, pr)
        await cache.get_issues_by_label("parked")

        fresh_pr = _pr()
        restored = _cache(tmp_path, fresh_pr)

        assert await restored.get_issues_by_label("parked") == _rows(1, 2)
        fresh_pr.list_issues_by_label.assert_not_awaited()

    async def test_invalidate_clears_issue_lists(self, tmp_path) -> None:
        pr = _pr(open_rows=_rows(1))
        cache = _cache(tmp_path, pr)
        await cache.get_issues_by_label("parked")

        cache.invalidate("issue_lists")
        await cache.get_issues_by_label("parked")
        assert pr.list_issues_by_label.await_count == 2

        cache.invalidate()
        assert cache._issue_lists == {}

    async def test_unsupported_state_raises(self, tmp_path) -> None:
        cache = _cache(tmp_path, _pr())
        with pytest.raises(ValueError, match="unsupported state"):
            await cache.get_issues_by_label("parked", state="all")


def _deps(*, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


class TestLoopDegradePaths:
    async def test_detector_degraded_empty_scan_never_autocloses(
        self, tmp_path
    ) -> None:
        """gh down past the grace → [] scan → auto-close MUST be skipped.

        Before #9814 an exception in the closed scan crashed the tick;
        with the cache degrading to [] instead, an unguarded auto-close
        pass would see zero churn and close EVERY open finding during a
        gh outage. The empty scan is treated as unreliable, same as a
        capped one.
        """
        from detector_calibration_loop import DetectorCalibrationLoop
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(repo_root=tmp_path / "repo")
        pr = _pr(open_rows=_rows(77))
        pr.list_closed_issues_by_label.side_effect = RuntimeError("gh down")
        pr.close_issue = AsyncMock()
        pr.post_comment = AsyncMock()

        loop = DetectorCalibrationLoop(
            config=cfg,
            state=MagicMock(),
            pr_manager=pr,
            deps=_deps(),
            github_cache=GitHubDataCache(
                cfg, pr, MagicMock(), cache_dir=tmp_path / "gh_cache"
            ),
        )
        # A tracked finding exists — the pre-#9814 failure mode would
        # close it off the degraded empty scan.
        loop._dedup.set_all({"detector_calibration:deadbeef0000"})

        stats = await loop._do_work()

        assert stats["closed_scanned"] == 0
        assert stats["autoclosed"] == 0
        pr.close_issue.assert_not_awaited()

    async def test_triage_tick_completes_when_gh_down_cold(self, tmp_path) -> None:
        """No snapshot + gh down → [] → the tick completes with zero scans."""
        from tests.helpers import ConfigFactory
        from triage_retry_loop import TriageRetryLoop

        cfg = ConfigFactory.create(repo_root=tmp_path / "repo")
        pr = _pr()
        pr.list_issues_by_label.side_effect = RuntimeError("gh down")
        state = MagicMock()
        state._data.triage_retry_attempts = {}

        loop = TriageRetryLoop(
            config=cfg,
            state=state,
            pr_manager=pr,
            deps=_deps(),
            github_cache=GitHubDataCache(
                cfg, pr, MagicMock(), cache_dir=tmp_path / "gh_cache"
            ),
        )

        stats = await loop._do_work()

        assert stats["scanned"] == 0
        assert stats["retried"] == 0
        assert stats["escalated"] == 0
