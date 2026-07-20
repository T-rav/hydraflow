"""DetectorCalibrationLoop — repeat-escalation churn miner (meta-observability).

The ADR-drift and fake-coverage FP campaigns each ran for weeks before a
human noticed the pattern: the same subject escalating repeatedly means the
DETECTOR is miscalibrated, not the code. This loop mines closed
``hitl-escalation`` issues, normalizes titles (digit runs → ``#`` so attempt
counts and elapsed times collapse), and files one ``detector-calibration``
find issue per subject that escalated >= 2 times inside the window.
Recursion stays bounded at one meta-layer (ADR-0045 §12.1): find issues
only, no escalation tier.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from detector_calibration_loop import DetectorCalibrationLoop, _normalize
from events import EventBus


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _closed(number: int, title: str, age_days: int = 1) -> dict:
    """Adapter-shaped closed-issue row: the churn window keys on
    ``closed_at`` (#9727); ``updated_at`` rides along for shape fidelity."""
    stamp = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    return {
        "number": number,
        "title": title,
        "body": "",
        "updated_at": stamp,
        "closed_at": stamp,
    }


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    pr.list_issues_by_label = AsyncMock(return_value=[])
    loop = DetectorCalibrationLoop(
        config=cfg, state=state, pr_manager=pr, deps=_deps(asyncio.Event())
    )
    return loop, pr


def test_normalize_collapses_volatile_numbers() -> None:
    a = _normalize(
        "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3"
    )
    b = _normalize(
        "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 7"
    )
    assert a == b
    c = _normalize("HITL: flaky test tests.a.test_x unresolved after 3 attempts")
    assert a != c


async def test_repeat_churn_files_calibration_issue(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(
            101,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
        ),
        _closed(
            102,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 6",
            age_days=10,
        ),
        _closed(103, "HITL: flaky test tests.a.test_x unresolved after 3 attempts"),
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 1
    title, body, labels = pr.create_issue.await_args.args
    assert "Detector calibration" in title
    assert "#101" in body
    assert "#102" in body
    assert "hydraflow-find" in labels
    assert "detector-calibration" in labels


async def test_below_threshold_is_noop(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(
            101,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
        ),
        _closed(103, "HITL: flaky test tests.a.test_x unresolved after 3 attempts"),
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_window_excludes_old_closes(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(
            101,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
        ),
        _closed(
            102,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 6",
            age_days=45,
        ),
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 0


async def test_dedup_prevents_refiling(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(101, "HITL: fake coverage gap X unresolved after 3"),
        _closed(102, "HITL: fake coverage gap X unresolved after 6"),
    ]
    await loop._do_work()
    await loop._do_work()
    assert pr.create_issue.await_count == 1


async def test_recovery_autocloses_when_churn_stops(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(101, "HITL: fake coverage gap X unresolved after 3"),
        _closed(102, "HITL: fake coverage gap X unresolved after 6"),
    ]
    await loop._do_work()
    filed_body = pr.create_issue.await_args.args[1]
    # Churn stops: the window rolls past the pair.
    pr.list_closed_issues_by_label.return_value = []
    pr.list_issues_by_label.return_value = [
        {"number": 77, "title": "whatever", "body": filed_body, "updated_at": ""}
    ]
    stats = await loop._do_work()
    pr.close_issue.assert_awaited_once_with(77)
    assert stats["autoclosed"] == 1
    # Re-armed: the same churn recurring later files fresh.
    pr.list_issues_by_label.return_value = []
    pr.list_closed_issues_by_label.return_value = [
        _closed(201, "HITL: fake coverage gap X unresolved after 3"),
        _closed(202, "HITL: fake coverage gap X unresolved after 9"),
    ]
    await loop._do_work()
    assert pr.create_issue.await_count == 2


async def test_kill_switch_short_circuits(tmp_path: Path) -> None:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    loop = DetectorCalibrationLoop(
        config=cfg,
        state=MagicMock(),
        pr_manager=AsyncMock(),
        deps=_deps(asyncio.Event(), enabled=False),
    )
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}


async def test_capped_scan_skips_autoclose(loop_env) -> None:
    """A truncated closed-issues scan can hide a still-churning subject —
    auto-closing on it would make the miner ITSELF churn (file → premature
    close → dedup re-arm → refile), the exact pathology it watches for."""
    from detector_calibration_loop import _SCAN_LIMIT

    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(101, "HITL: fake coverage gap X unresolved after 3"),
        _closed(102, "HITL: fake coverage gap X unresolved after 6"),
    ]
    await loop._do_work()
    filed_body = pr.create_issue.await_args.args[1]

    # Next tick: scan comes back AT the cap and the churning subject is
    # absent from it — indistinguishable from recovery. Must NOT close.
    capped = [
        _closed(1000 + i, f"HITL: trust-loop anomaly — w{i} kind{i}")
        for i in range(_SCAN_LIMIT)
    ]
    pr.list_closed_issues_by_label.return_value = capped
    pr.list_issues_by_label.return_value = [
        {"number": 77, "title": "t", "body": filed_body, "updated_at": ""}
    ]
    stats = await loop._do_work()
    pr.close_issue.assert_not_awaited()
    assert stats["autoclosed"] == 0
