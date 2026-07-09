"""Unit tests for MergeStateWatcherLoop (advisor-2mf coverage gap).

Closes the unit-test gap identified in the coverage matrix audit.  The
watcher's underlying logic is already covered by ``test_merge_state_watcher.py``;
these tests focus on the loop shell: enabled/disabled path, default interval,
and that ``_do_work`` delegates to and propagates the watcher's stats.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from approval_records import ApprovalRecordReconciler
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus, EventType
from merge_state_watcher_loop import MergeStateWatcherLoop


def _stub_reconciler(
    result: dict | None = None, error: Exception | None = None
) -> MagicMock:
    """Approval-record reconciler stub (keeps unit tests off the gh boundary)."""
    reconciler = MagicMock()
    if error is not None:
        reconciler.reconcile = AsyncMock(side_effect=error)
    else:
        reconciler.reconcile = AsyncMock(
            return_value=result
            if result is not None
            else {"merged_seen": 0, "recorded": 0}
        )
    return reconciler


def _make_loop(
    tmp_path,
    *,
    enabled: bool = True,
    conflicting_prs: list | None = None,
    rebase_result: bool = True,
    mergeable: bool = True,
    reconciler: MagicMock | None = None,
    bus: EventBus | None = None,
    data_root=None,
) -> MergeStateWatcherLoop:
    """Factory: return a MergeStateWatcherLoop with stubbed dependencies."""
    if data_root is not None:
        cfg = HydraFlowConfig(repo="acme/widgets", data_root=data_root)
    else:
        cfg = HydraFlowConfig(repo="acme/widgets")
    stop = asyncio.Event()
    stop.set()
    deps = LoopDeps(
        event_bus=bus if bus is not None else EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: enabled or name != "merge_state_watcher",
    )
    prs = AsyncMock()
    prs.list_conflicting_prs = AsyncMock(return_value=conflicting_prs or [])
    prs.update_pr_branch = AsyncMock(return_value=rebase_result)
    prs.get_pr_mergeable = AsyncMock(return_value=mergeable)
    prs.add_pr_labels = AsyncMock()
    return MergeStateWatcherLoop(
        config=cfg,
        prs=prs,
        deps=deps,
        approval_reconciler=reconciler
        if reconciler is not None
        else _stub_reconciler(),
    )


class TestMergeStateWatcherLoopShell:
    """Loop shell: enabled/disabled gate, default interval, stats pass-through."""

    async def test_disabled_via_kill_switch_returns_disabled_status(
        self, tmp_path
    ) -> None:
        """When the kill-switch is off the loop short-circuits without calling prs."""
        loop = _make_loop(tmp_path, enabled=False)
        result = await loop._do_work()
        assert result == {"status": "disabled"}

    async def test_default_interval_is_ten_minutes(self, tmp_path) -> None:
        """The default poll cadence is 600 s (10 min)."""
        loop = _make_loop(tmp_path)
        assert loop._get_default_interval() == 600

    async def test_worker_name_is_merge_state_watcher(self, tmp_path) -> None:
        """Worker name must match the constant used for kill-switch routing."""
        loop = _make_loop(tmp_path)
        assert loop._worker_name == "merge_state_watcher"

    async def test_no_conflicting_prs_returns_zero_stats(self, tmp_path) -> None:
        """Empty conflict list propagates as all-zero stats dict."""
        loop = _make_loop(tmp_path, conflicting_prs=[])
        result = await loop._do_work()
        assert result is not None
        assert result["checked"] == 0
        assert result["rebased"] == 0
        assert result["escalated"] == 0
        assert result["skipped"] == 0

    async def test_one_rebased_pr_reflected_in_stats(self, tmp_path) -> None:
        """One conflicting PR that rebases cleanly: checked=1, rebased=1."""
        from merge_state_watcher import ConflictingPR  # noqa: PLC0415

        pr = ConflictingPR(number=42, branch="feat/x", labels=[])
        loop = _make_loop(
            tmp_path,
            conflicting_prs=[pr],
            rebase_result=True,
            mergeable=True,
        )
        result = await loop._do_work()
        assert result is not None
        assert result["checked"] == 1
        assert result["rebased"] == 1
        assert result["escalated"] == 0

    async def test_unresolvable_conflict_escalated(self, tmp_path) -> None:
        """PR that cannot be rebased is escalated (HITL label applied)."""
        from merge_state_watcher import ConflictingPR  # noqa: PLC0415

        pr = ConflictingPR(number=99, branch="feat/y", labels=[])
        loop = _make_loop(
            tmp_path,
            conflicting_prs=[pr],
            rebase_result=False,
            mergeable=False,
        )
        result = await loop._do_work()
        assert result is not None
        assert result["escalated"] == 1
        assert result["rebased"] == 0


class TestApprovalReconcilerIntegration:
    """CH-2 (#9730): the loop hosts the approval-record reconciler tick."""

    async def test_do_work_includes_approval_counters(self, tmp_path) -> None:
        """Reconciler counters ride the loop's status dict under 'approvals'."""
        reconciler = _stub_reconciler({"merged_seen": 3, "recorded": 2})
        loop = _make_loop(tmp_path, reconciler=reconciler)
        result = await loop._do_work()
        assert result is not None
        assert result["approvals"] == {"merged_seen": 3, "recorded": 2}
        reconciler.reconcile.assert_awaited_once()

    async def test_kill_switch_skips_reconciler(self, tmp_path) -> None:
        """The loop-level kill-switch also gates approval reconciliation."""
        reconciler = _stub_reconciler()
        loop = _make_loop(tmp_path, enabled=False, reconciler=reconciler)
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        reconciler.reconcile.assert_not_awaited()

    async def test_reconciler_error_propagates_after_unstick(self, tmp_path) -> None:
        """gh outage in the reconciler propagates to the loop cycle handler
        (no broad except); conflict unsticking has already run."""
        reconciler = _stub_reconciler(error=RuntimeError("gh: HTTP 502"))
        loop = _make_loop(tmp_path, reconciler=reconciler)
        with pytest.raises(RuntimeError, match="502"):
            await loop._do_work()
        loop._watcher._prs.list_conflicting_prs.assert_awaited_once()

    async def test_default_constructs_real_reconciler(self, tmp_path) -> None:
        """Without injection the loop builds an ApprovalRecordReconciler
        from its config (production wiring in service_registry)."""
        cfg = HydraFlowConfig(repo="acme/widgets")
        stop = asyncio.Event()
        stop.set()
        deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=stop,
            status_cb=lambda *a, **k: None,
            enabled_cb=lambda _name: True,
        )
        loop = MergeStateWatcherLoop(config=cfg, prs=AsyncMock(), deps=deps)
        assert isinstance(loop._approvals, ApprovalRecordReconciler)


def _drain_alerts(queue) -> list:
    """Drain a subscriber queue, keeping only SYSTEM_ALERT events."""
    alerts = []
    while not queue.empty():
        event = queue.get_nowait()
        if event.type is EventType.SYSTEM_ALERT:
            alerts.append(event)
    return alerts


class TestCaptureGapAlert:
    """A capture-gap tick surfaces loudly (review finding): one DedupStore'd
    SYSTEM_ALERT per gap event, re-armed by a clean tick."""

    async def test_capture_gap_publishes_one_deduped_system_alert(
        self, tmp_path
    ) -> None:
        bus = EventBus()
        queue = bus.subscribe()
        loop = _make_loop(
            tmp_path,
            reconciler=_stub_reconciler(
                {"merged_seen": 3, "recorded": 3, "capture_gap_risk": True}
            ),
            bus=bus,
            data_root=tmp_path / "data",
        )

        await loop._do_work()
        await loop._do_work()  # same ongoing gap event — deduped

        alerts = _drain_alerts(queue)
        assert len(alerts) == 1
        assert alerts[0].data["kind"] == "approval_records_capture_gap"

    async def test_capture_gap_alert_rearms_after_clean_tick(self, tmp_path) -> None:
        bus = EventBus()
        queue = bus.subscribe()
        reconciler = MagicMock()
        reconciler.reconcile = AsyncMock(
            side_effect=[
                {"merged_seen": 1, "recorded": 1, "capture_gap_risk": True},
                {"merged_seen": 1, "recorded": 0, "capture_gap_risk": False},
                {"merged_seen": 1, "recorded": 1, "capture_gap_risk": True},
            ]
        )
        loop = _make_loop(
            tmp_path, reconciler=reconciler, bus=bus, data_root=tmp_path / "data"
        )

        for _ in range(3):
            await loop._do_work()

        assert len(_drain_alerts(queue)) == 2
