"""Tests for PrinciplesAuditLoop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from principles_audit_loop import PrinciplesAuditLoop


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    cfg.managed_repos = []
    state = MagicMock()
    state.blocked_slugs.return_value = set()
    state.get_onboarding_status.return_value = None
    state.get_last_green_audit.return_value = {}
    state.get_drift_attempts.return_value = 0
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    return cfg, state, pr_manager


def test_skeleton_worker_name_and_interval(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        deps=_deps(stop),
    )
    assert loop._worker_name == "principles_audit"  # type: ignore[attr-defined]
    assert loop._get_default_interval() == 604800  # spec §4.4
