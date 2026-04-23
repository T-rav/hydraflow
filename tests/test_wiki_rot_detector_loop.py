"""Tests for WikiRotDetectorLoop (spec §4.9)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from wiki_rot_detector_loop import WikiRotDetectorLoop


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
    state.get_wiki_rot_attempts.return_value = 0
    state.inc_wiki_rot_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    wiki_store = MagicMock()
    wiki_store.list_repos.return_value = []
    return cfg, state, pr_manager, dedup, wiki_store


def _loop(env, *, enabled: bool = True) -> WikiRotDetectorLoop:
    cfg, state, pr, dedup, wiki_store = env
    return WikiRotDetectorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        wiki_store=wiki_store,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "wiki_rot_detector"
    assert loop._get_default_interval() == 604800


async def test_do_work_noop_when_no_repos(loop_env) -> None:
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "noop"
    assert stats["repos_scanned"] == 0
    _, _, pr, _, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_do_work_disabled_short_circuits(loop_env) -> None:
    loop = _loop(loop_env, enabled=False)
    # The base class short-circuits ``run``, not ``_do_work``; we test the
    # explicit kill-switch guard at the top of ``_do_work``.
    stats = await loop._do_work()
    assert stats["status"] == "disabled"
