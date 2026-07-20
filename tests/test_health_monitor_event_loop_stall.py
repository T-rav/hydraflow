"""HealthMonitor escalation for EventLoopWatchdog stall markers (#9552).

The watchdog THREAD can only leave a marker on disk (Ports are async and run
on the very event loop that froze); this suite covers the consumer side —
``HealthMonitorLoop._check_event_loop_stall`` filing one ``hydraflow-find``
+ ``loop-stalled`` issue per marker and consuming it file-then-clear.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from event_loop_watchdog import (
    event_loop_stall_marker_path,
    read_stall_marker,
    write_stall_marker,
)
from health_monitor_loop import HealthMonitorLoop

_MARKER_PAYLOAD = {
    "detected_at": "2026-07-20T00:00:00+00:00",
    "stalled_for_seconds": 245.0,
    "threshold_seconds": 120.0,
    "pid": 4242,
    "dump_path": "/data/diagnostics/event_loop_stall_20260720T000000Z.txt",
    "hard_restart": False,
    "episode_count": 2,
}


@pytest.fixture
def hm_env(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=repo_root,
    )
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=42)
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._prs = prs
    return hm, cfg, prs


async def test_no_marker_is_silent_noop(hm_env) -> None:
    hm, _cfg, prs = hm_env
    await hm._check_event_loop_stall()
    prs.create_issue.assert_not_awaited()


async def test_marker_files_issue_and_is_consumed(hm_env) -> None:
    hm, cfg, prs = hm_env
    marker_path = event_loop_stall_marker_path(cfg)
    write_stall_marker(marker_path, dict(_MARKER_PAYLOAD))

    await hm._check_event_loop_stall()

    prs.create_issue.assert_awaited_once()
    title, body, labels = prs.create_issue.await_args.args
    assert "event-loop-stalled" in title
    assert "245.0" in title
    assert labels == ["hydraflow-find", "loop-stalled"]
    assert "event_loop_stall_20260720T000000Z.txt" in body
    assert "#9552" in body
    # Consumed: the marker file itself is the dedup — a second tick is a noop.
    assert read_stall_marker(marker_path) is None
    await hm._check_event_loop_stall()
    prs.create_issue.assert_awaited_once()


async def test_failed_filing_retains_marker_for_retry(hm_env) -> None:
    hm, cfg, prs = hm_env
    marker_path = event_loop_stall_marker_path(cfg)
    write_stall_marker(marker_path, dict(_MARKER_PAYLOAD))
    prs.create_issue.side_effect = RuntimeError("gh unavailable")

    with pytest.raises(RuntimeError):
        await hm._check_event_loop_stall()

    # File-then-clear: the filing failed, so the marker must survive.
    assert read_stall_marker(marker_path) is not None


async def test_no_prs_dependency_is_silent_noop_and_retains_marker(hm_env) -> None:
    hm, cfg, _prs = hm_env
    hm._prs = None
    marker_path = event_loop_stall_marker_path(cfg)
    write_stall_marker(marker_path, dict(_MARKER_PAYLOAD))
    await hm._check_event_loop_stall()
    assert read_stall_marker(marker_path) is not None


async def test_corrupt_marker_is_treated_as_absent(hm_env) -> None:
    hm, cfg, prs = hm_env
    marker_path = event_loop_stall_marker_path(cfg)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("{not json", encoding="utf-8")
    await hm._check_event_loop_stall()
    prs.create_issue.assert_not_awaited()
