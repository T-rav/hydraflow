"""Tests for FlakeTrackerLoop (spec §4.5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from flake_tracker_loop import FlakeTrackerLoop, parse_junit_xml


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
    state = MagicMock()
    state.get_flake_counts.return_value = {}
    state.get_flake_attempts.return_value = 0
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr_manager, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "flake_tracker"
    assert loop._get_default_interval() == 14400


def test_parse_junit_xml_counts_failures_per_test() -> None:
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="tests.scenarios" name="test_alpha" />
    <testcase classname="tests.scenarios" name="test_bravo">
      <failure message="AssertionError"/>
    </testcase>
    <testcase classname="tests.scenarios" name="test_charlie">
      <error message="Timeout"/>
    </testcase>
  </testsuite>
</testsuites>
"""
    results = parse_junit_xml(xml)
    assert results == {
        "tests.scenarios.test_alpha": "pass",
        "tests.scenarios.test_bravo": "fail",
        "tests.scenarios.test_charlie": "fail",
    }
