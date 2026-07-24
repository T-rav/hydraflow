"""Regression test for issue #10394.

Bug: closing an issue flipped its state but did NOT strip its pipeline-stage
labels. Issue #10314 was implemented, merged, and closed at
``2026-07-23T04:17:17Z`` — yet it still carried ``hydraflow-ready`` — and
~23h later a dispatcher stamped ``hydraflow-in-progress`` on the CLOSED issue
and re-ran a full plan/implement cycle. The exact timeline:

    2026-07-22T18:45:32Z labeled hydraflow-ready
    2026-07-23T04:17:17Z closed
    2026-07-24T03:41:31Z labeled hydraflow-in-progress   <-- on a CLOSED issue

Root cause: a work-picker queues by label presence without checking
``state: OPEN``, so a closed issue that still carries ``hydraflow-ready``
stays a redispatch candidate forever.

Three layered defenses pin the fix here (all assert post-fix behaviour, so
they are GREEN once the fix lands):

(a) ``PRManager.close_issue`` strips active stage labels at close — modelled
    via the FakeGitHub mirror (``close_issue`` drops ``hydraflow-*`` non-terminal
    labels).
(b) The ready-scan fetcher filters ``state: OPEN`` — a closed-but-labeled
    issue is never dispatched (``IssueFetcher._is_open``).
(c) The ``LabelDriftWatcherLoop`` (ADR-0088) is the belt-and-suspenders for a
    GitHub-native ``Closes #N`` auto-close that bypasses ``close_issue``: it
    detects the closed+labeled issue and strips the stale label.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from issue_fetcher import IssueFetcher
from label_drift_watcher_loop import LabelDriftWatcherLoop
from mockworld.fakes import FakeGitHub


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *_a, **_k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.mark.asyncio
async def test_10394_hydraflow_close_strips_stage_label() -> None:
    """(a) A HydraFlow-initiated close drops the active stage label; the
    terminal ``hydraflow-fixed`` marker survives."""
    gh = FakeGitHub()
    gh.add_issue(
        10314, "shipped work", "body", labels=["hydraflow-ready", "hydraflow-fixed"]
    )

    await gh.close_issue(10314)

    labels = gh._issues[10314].labels
    assert "hydraflow-ready" not in labels, "active stage label must be stripped"
    assert "hydraflow-fixed" in labels, "terminal marker must be preserved"


@pytest.mark.asyncio
async def test_10394_ready_scan_excludes_closed_labeled_issue(
    tmp_path: Path, monkeypatch
) -> None:
    """(b) The ready-work fetcher never dispatches a CLOSED issue, even when
    it still carries ``hydraflow-ready`` (the #10314 stale-label state)."""
    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="test-org/test-repo", repo_root=tmp_path
    )
    fetcher = IssueFetcher(cfg)

    # A stale gh --cache snapshot / native auto-close leaves the closed issue
    # still matching the hydraflow-ready label scan.
    raw = (
        '[{"number": 10314, "title": "shipped", "body": "", '
        '"labels": [{"name": "' + cfg.ready_label[0] + '"}], '
        '"comments": [], "url": "", "state": "closed"}]'
    )

    async def _fake_run(*_a, **_k):
        return raw

    monkeypatch.setattr("issue_fetcher.run_subprocess", _fake_run)

    issues = await fetcher.fetch_ready_issues(set())

    assert all(i.number != 10314 for i in issues), (
        "a CLOSED issue must never be dispatched even with hydraflow-ready (#10394)"
    )


@pytest.mark.asyncio
async def test_10394_drift_watcher_strips_native_close_stale_label(
    tmp_path: Path,
) -> None:
    """(c) The exact #10314 sequence: label→closed (native, label retained)→
    the watcher strips the stale stage label so the later re-label/redispatch
    can never happen."""
    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="test-org/test-repo", repo_root=tmp_path
    )
    gh = FakeGitHub()
    # labeled hydraflow-ready, still OPEN
    gh.add_issue(10314, "shipped work", "body", labels=["hydraflow-ready"])
    # GitHub-native `Closes #10314` auto-close: state flips but the label is
    # NOT stripped (this bypasses PRManager.close_issue entirely).
    gh._issues[10314].state = "closed"
    assert "hydraflow-ready" in gh._issues[10314].labels  # the #10314 gap

    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=gh, deps=_deps(asyncio.Event()))
    stats = await loop._do_work()

    assert stats["closed_stale_detected"] == 1
    assert stats["closed_stale_stripped"] == 1
    assert "hydraflow-ready" not in gh._issues[10314].labels, (
        "watcher must strip the stale stage label from the closed issue"
    )
    # A comment records the correction, referencing the issue.
    assert any(num == 10314 for num, _body in gh._comments)
