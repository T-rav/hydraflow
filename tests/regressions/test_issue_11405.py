"""Regression pin for #11405: normalize must not fold distinct PR identity.

Live incident: the same escalation subject ("Sampled re-audit disagreement:
PR ## (gauntlet) — adversarial re-review flags a possible silent escape")
closed and re-fired 3 times in 30 days for THREE DIFFERENT PRs (#10817,
#11241, #11242). ``DetectorCalibrationLoop._normalize()`` collapsed every
digit run — including the ``#{pr_number}`` that is the subject's actual
identity — to a bare ``#``, so three distinct one-time escalations mined
into one fabricated "churn" finding. The detector was miscalibrated, not
the escalations.

Fix: ``_normalize`` must treat a ``#``-prefixed digit run as entity
identity (issue/PR reference) and preserve it verbatim; only bare digit
runs (attempt counts, elapsed seconds) collapse to ``#``.
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
    stamp = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    return {
        "number": number,
        "title": title,
        "body": "",
        "updated_at": stamp,
        "closed_at": stamp,
    }


def _sampled_audit_title(pr_number: int) -> str:
    return (
        f"Sampled re-audit disagreement: PR #{pr_number} "
        "(gauntlet) — adversarial re-review flags a possible silent escape"
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    from github_cache_loop import GitHubDataCache

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


def test_normalize_preserves_distinct_pr_identity() -> None:
    a = _normalize(_sampled_audit_title(10817))
    b = _normalize(_sampled_audit_title(11241))
    c = _normalize(_sampled_audit_title(11242))
    assert a != b
    assert b != c
    assert a != c


async def test_distinct_prs_do_not_file_fabricated_churn(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(10817, _sampled_audit_title(10817), age_days=20),
        _closed(11241, _sampled_audit_title(11241), age_days=10),
        _closed(11242, _sampled_audit_title(11242), age_days=1),
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 0


async def test_same_pr_repeated_escalation_still_files(loop_env) -> None:
    """Counter-pin: real churn (same PR closing and re-firing) must still file."""
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(10817, _sampled_audit_title(10817), age_days=20),
        _closed(10817, _sampled_audit_title(10817), age_days=1),
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 1


def test_bare_digit_runs_still_collapse_to_hash() -> None:
    """Counter-pin: volatile bare counters (no ``#`` prefix) keep collapsing."""
    a = _normalize(
        "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3"
    )
    b = _normalize(
        "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 7"
    )
    assert a == b
