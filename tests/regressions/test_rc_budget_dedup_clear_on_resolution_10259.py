"""Regression #10259: rc_budget must re-fire after its tracking issue closes.

Bug (2) of the #10215 pair: the ``rc_budget:{kind}`` dedup key, once set on
the first fire, blocks every subsequent tick's ``if key in dedup: continue``
guard in ``_do_work``. If closing the first-tier ``rc-duration-regression``
issue never cleared that key, the detector would go **permanently blind** for
that ``kind`` after firing once — a genuine later regression of the same kind
could never be reported again.

The clear-path itself (``RCBudgetLoop._reconcile_closed_regressions``) landed
with #10256 and is unit-tested in ``tests/test_rc_budget_loop.py``. What was
missing — and what #10259's acceptance criteria explicitly names — is an
**end-to-end lifecycle** guard driven through ``_do_work`` proving the whole
loop: fire (dedup key set) → key holds while the issue is OPEN (no duplicate
refile) → issue CLOSED by a human → next tick CLEARS the key → a still-present
breach RE-FIRES a fresh ``rc-duration-regression`` issue.

This uses a REAL :class:`DedupStore` (file-backed) so the key genuinely
persists across ticks — a MagicMock dedup would mask the very cross-tick
behaviour under test. If the clear-path is ever removed, tick 3 below skips
instead of refiling and the ``filed`` / ``create_issue`` assertions fail:
this is a behavioural guard, not a tautology.

Sibling: ``test_rc_budget_cancelled_run_misclassification_10215.py`` covers
bug (1) — cancelled runs polluting the baseline.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from rc_budget_loop import RCBudgetLoop

_MEDIAN_KEY = "rc_budget:median"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _breaching_runs() -> list[dict[str, object]]:
    """One newest 500s run over six 300s history runs.

    median(others)=300 → median fires at 1.5*300=450s (500>=450). recent_max=300
    → spike fires at 2.0*300=600s (500<600 → NOT tripped), so exactly ONE signal
    (``median``) fires and the test tracks a single dedup key.

    Timestamps are relative to ``now`` (not hardcoded calendar dates) so the
    fixture stays inside ``RCBudgetLoop``'s 30-day rolling window regardless
    of when the test runs — a hardcoded date ages out of that window and
    silently drops ``runs_seen`` below ``_MIN_HISTORY``, flipping the loop
    into ``"warmup"`` instead of ``"ok"``.
    """
    now = datetime.now(UTC)
    history = [
        {
            "id": 1000 + i,
            "url": f"https://example/run/{1000 + i}",
            "status": "completed",
            "conclusion": "success",
            "created_at": _iso(now - timedelta(days=7 - i)),
            "run_started_at": _iso(now - timedelta(days=7 - i)),
            "updated_at": _iso(now - timedelta(days=7 - i) + timedelta(seconds=300)),
        }
        for i in range(1, 7)
    ]
    current = {
        "id": 2500,
        "url": "https://example/run/2500",
        "status": "completed",
        "conclusion": "success",
        "created_at": _iso(now),
        "run_started_at": _iso(now),
        "updated_at": _iso(now + timedelta(seconds=500)),
    }
    return [current, *history]


async def test_dedup_key_clears_on_issue_close_and_breach_refires(
    tmp_path: Path, monkeypatch,
) -> None:
    """Full fire → hold-while-open → close → clear → re-fire lifecycle."""
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")

    # Real, file-backed dedup so the key persists across ticks (the behaviour
    # under test). A MagicMock would return a fixed set and hide the clear.
    dedup = DedupStore("rc_budget", tmp_path / "rc_budget_dedup.json")

    # Attempts climb for real: tick 1 -> 1, re-fire tick -> 2, both < 3 so each
    # files a regression issue (not an escalation). clear_rc_budget_attempts is
    # asserted NEVER called: a first-tier close clears the KEY, never the ladder.
    attempts = {"median": 0}

    def _inc(kind: str) -> int:
        attempts[kind] += 1
        return attempts[kind]

    state = MagicMock()
    state.get_rc_budget_duration_history.return_value = []
    state.get_rc_budget_attempts.return_value = 0
    state.inc_rc_budget_attempts.side_effect = _inc

    # Human closes the first-tier regression issue between tick 2 and tick 3.
    issue_closed = {"value": False}

    async def fake_list_closed(label: str, **_kwargs: object) -> list[dict]:
        if label == "rc-duration-regression" and issue_closed["value"]:
            return [
                {
                    "number": 10259,
                    "title": "RC gate duration regression: 500s vs 300s (median)",
                    "body": "",
                    "labels": [],  # no bot marker => human close => clears key
                }
            ]
        return []

    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=4242)
    pr.list_closed_issues_by_label = AsyncMock(side_effect=fake_list_closed)
    # Gate-only classification fetch: empty jobs => fail-open => full run
    # (included in the baseline). Never a raw subprocess.
    pr.get_workflow_run_jobs = AsyncMock(return_value=[])

    github_cache = MagicMock()
    github_cache.get_rc_workflow_runs = AsyncMock(return_value=_breaching_runs())

    loop = RCBudgetLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        deps=LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=lambda *a, **k: None,
            enabled_cb=lambda _name: True,
        ),
        github_cache=github_cache,
    )
    # Air-gap: the whole lifecycle must route through the PRPort + cache, never
    # a raw gh subprocess.
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])

    def _no_subprocess(*_a: object, **_k: object) -> None:
        raise AssertionError("rc_budget lifecycle must not spawn a raw subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_subprocess)

    # Tick 1: breach detected, no prior key -> file + set rc_budget:median.
    stats1 = await loop._do_work()
    assert stats1["status"] == "ok", stats1
    assert stats1["filed"] == 1, stats1
    assert _MEDIAN_KEY in dedup.get()
    assert pr.create_issue.await_count == 1

    # Tick 2: issue still OPEN, key still set -> breach re-detected but SKIPPED
    # (fire-once-while-open). No duplicate issue.
    stats2 = await loop._do_work()
    assert stats2["filed"] == 0, stats2
    assert _MEDIAN_KEY in dedup.get()
    assert pr.create_issue.await_count == 1  # unchanged: no refile while open

    # Human resolves the regression by closing the tracking issue.
    issue_closed["value"] = True

    # Tick 3: reconcile clears the key, the still-present breach RE-FIRES.
    stats3 = await loop._do_work()
    assert stats3["filed"] == 1, stats3
    assert _MEDIAN_KEY in dedup.get()  # re-armed by the re-fire
    assert pr.create_issue.await_count == 2  # a fresh regression issue filed

    # The re-fire is a first-tier regression issue, not an escalation.
    last_labels = pr.create_issue.await_args_list[-1].args[2]
    assert "rc-duration-regression" in last_labels
    assert "hitl-escalation" not in last_labels

    # A first-tier close clears the KEY only — never the attempts ladder
    # (spec §3.2: only the terminal rc-duration-stuck escalation resets it).
    state.clear_rc_budget_attempts.assert_not_called()
    assert attempts["median"] == 2  # ladder climbed 1 -> 2, ready for escalation
