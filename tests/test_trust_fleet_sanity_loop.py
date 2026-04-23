"""Tests for TrustFleetSanityLoop (spec §12.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from trust_fleet_sanity_loop import TrustFleetSanityLoop


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_trust_fleet_sanity_attempts.return_value = 0
    state.inc_trust_fleet_sanity_attempts.return_value = 1
    state.get_trust_fleet_sanity_last_run.return_value = None
    state.get_trust_fleet_sanity_last_seen_counts.return_value = {}
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {}
    bg_workers.get_interval.return_value = 600
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = EventBus()
    return cfg, state, bg_workers, pr_manager, dedup, bus


def _loop(env, enabled: bool = True) -> TrustFleetSanityLoop:
    cfg, state, bg_workers, pr, dedup, bus = env
    deps = _deps(asyncio.Event(), enabled=enabled)
    return TrustFleetSanityLoop(
        config=cfg,
        state=state,
        bg_workers=bg_workers,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        deps=deps,
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "trust_fleet_sanity"
    assert loop._get_default_interval() == 600


async def test_do_work_noop_when_no_metrics(loop_env) -> None:
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "ok"
    assert stats["anomalies"] == 0
    _, _, _, pr, _, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_kill_switch_short_circuits(loop_env) -> None:
    loop = _loop(loop_env, enabled=False)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "disabled"
