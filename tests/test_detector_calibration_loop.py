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
    from github_cache_loop import GitHubDataCache

    # TTL 0 (#9814): every cached read refreshes through the pr mock so
    # per-test return_value mutations stay visible tick-to-tick.
    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", github_cache_issue_list_ttl_s=0
    )
    state = MagicMock()
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    pr.list_issues_by_label = AsyncMock(return_value=[])
    loop = DetectorCalibrationLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        deps=_deps(asyncio.Event()),
        github_cache=GitHubDataCache(cfg, pr, MagicMock()),
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
    # Churn stops: the window rolls past the pair. The rows STAY in the
    # scan (the 500-row closed scan is not date-filtered — only the in-loop
    # cutoff excludes them); an empty scan now means "gh degraded" and
    # skips auto-close entirely (#9814).
    pr.list_closed_issues_by_label.return_value = [
        _closed(101, "HITL: fake coverage gap X unresolved after 3", age_days=45),
        _closed(102, "HITL: fake coverage gap X unresolved after 6", age_days=45),
    ]
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
    from github_cache_loop import GitHubDataCache

    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", github_cache_issue_list_ttl_s=0
    )
    pr = AsyncMock()
    loop = DetectorCalibrationLoop(
        config=cfg,
        state=MagicMock(),
        pr_manager=pr,
        deps=_deps(asyncio.Event(), enabled=False),
        github_cache=GitHubDataCache(cfg, pr, MagicMock()),
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


async def test_per_tick_cap_folds_overflow_into_one_summary(loop_env) -> None:
    """#10777: >cap churning subjects file `cap` issues + ONE summary, not N."""
    loop, pr = loop_env
    cap = loop._config.detector_calibration_max_issues_per_tick
    n_subjects = cap + 3
    closed = []
    num = 500
    for i in range(n_subjects):
        # Distinct non-numeric subject slugs → distinct normalized subjects;
        # two closes each puts every subject over the churn threshold.
        subj = (
            f"HITL: fake coverage gap FakeGitHub:surface-{chr(97 + i)} unresolved after"
        )
        closed.append(_closed(num, f"{subj} 3"))
        closed.append(_closed(num + 1, f"{subj} 6", age_days=2))
        num += 2
    pr.list_closed_issues_by_label.return_value = closed

    stats = await loop._do_work()

    # cap individual issues + exactly one summary issue.
    assert pr.create_issue.await_count == cap + 1
    assert stats["filed"] == cap + 1
    summaries = [
        c.args[0]
        for c in pr.create_issue.await_args_list
        if "over per-tick filing cap" in c.args[0]
    ]
    assert len(summaries) == 1


async def test_at_cap_files_no_summary(loop_env) -> None:
    """Exactly `cap` churning subjects → all filed individually, no summary."""
    loop, pr = loop_env
    cap = loop._config.detector_calibration_max_issues_per_tick
    closed = []
    num = 700
    for i in range(cap):
        subj = (
            f"HITL: fake coverage gap FakeGitHub:region-{chr(97 + i)} unresolved after"
        )
        closed.append(_closed(num, f"{subj} 3"))
        closed.append(_closed(num + 1, f"{subj} 6", age_days=2))
        num += 2
    pr.list_closed_issues_by_label.return_value = closed

    stats = await loop._do_work()

    assert pr.create_issue.await_count == cap
    assert stats["filed"] == cap
    assert not any(
        "over per-tick filing cap" in c.args[0] for c in pr.create_issue.await_args_list
    )
