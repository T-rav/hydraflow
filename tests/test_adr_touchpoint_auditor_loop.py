"""Unit tests for AdrTouchpointAuditorLoop (ADR-0056 + #8987 rollup).

Per-ADR rollup behavior (#8987): one issue per ADR listing all PRs that
drifted it. Subsequent ticks update the body. Dedup key is
``adr_touchpoint_auditor:ADR-NNNN`` (no PR component).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from adr_touchpoint_auditor_loop import AdrTouchpointAuditorLoop
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _write_adr(adr_dir: Path, *, number: int, title: str, related: list[str]) -> None:
    related_block = ", ".join(f"`{f}`" for f in related)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related_block}\n\n"
        f"## Context\n\nFixture body.\n"
    )
    (adr_dir / f"{number:04d}-{title.lower()}.md").write_text(body)


def _state_mock() -> MagicMock:
    """Build a MagicMock state with rollup-aware defaults."""
    state = MagicMock()
    state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00+00:00"
    state.get_adr_audit_attempts.return_value = 0
    state.inc_adr_audit_attempts.return_value = 1
    state.get_adr_rollup.return_value = None
    return state


@pytest.fixture
def loop_env(tmp_path: Path):
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
    _write_adr(adr_dir, number=27, title="beta", related=["src/runner.py"])

    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
    )
    state = _state_mock()
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.update_issue_body = AsyncMock(return_value=None)
    pr.close_issue = AsyncMock(return_value=None)
    dedup = MagicMock()
    dedup.get.return_value = set()

    from adr_index import ADRIndex  # noqa: PLC0415

    return cfg, state, pr, dedup, ADRIndex(adr_dir)


def test_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    assert loop._worker_name == "adr_touchpoint_auditor"
    assert loop._get_default_interval() == 14400


async def test_first_run_seeds_cursor_and_returns(loop_env) -> None:
    """Empty cursor → seed it to 'now' and bail; no scan, no issues."""
    cfg, state, pr, dedup, idx = loop_env
    state.get_adr_audit_cursor.return_value = ""

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    result = await loop._do_work()
    assert result == {"status": "seeded", "filed": 0, "scanned": 0}
    state.set_adr_audit_cursor.assert_called_once()
    pr.create_issue.assert_not_awaited()


async def test_drift_files_one_rollup_per_adr(loop_env, monkeypatch) -> None:
    """A merged PR touching an ADR-cited src/ file → 1 rollup issue."""
    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8473,
                "mergedAt": "2026-05-06T20:00:00Z",
                "title": "feat: tweak",
                "files": [
                    {"path": "src/agent.py"},
                    {"path": "tests/test_agent.py"},
                ],
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["scanned"] == 1
    assert stats["filed"] == 1
    assert stats["updated"] == 0
    assert stats["escalated"] == 0
    title = pr.create_issue.await_args.args[0]
    body = pr.create_issue.await_args.args[1]
    assert "ADR-0024" in title
    assert "1 PR" in title  # rollup count
    assert "PR #8473" in title or "#8473" in body
    # Rollup state was recorded so the next tick can update in-place.
    state.set_adr_rollup.assert_called_once()
    call_kwargs = state.set_adr_rollup.call_args.kwargs
    assert call_kwargs["pr_numbers"] == [8473]
    assert call_kwargs["issue_number"] == 42


async def test_rollup_zero_sentinel_does_not_record_or_dedup(
    loop_env, monkeypatch
) -> None:
    """create_issue's 0 sentinel must not record a rollup or add the dedup key.

    Regression for issue #9241: a failed gh call returns 0; recording
    ``issue_number=0`` or adding the dedup key would suppress re-filing
    forever (next tick's ``dedup_key in dedup`` skips) without a real issue.
    """
    cfg, state, pr, dedup, idx = loop_env
    pr.create_issue = AsyncMock(return_value=0)  # gh failed → sentinel
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8473,
                "mergedAt": "2026-05-06T20:00:00Z",
                "title": "feat: tweak",
                "files": [{"path": "src/agent.py"}],
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()

    pr.create_issue.assert_awaited()  # it tried
    assert stats["filed"] == 0  # but recorded nothing
    state.set_adr_rollup.assert_not_called()
    dedup.set_all.assert_not_called()  # no dedup add — retries next cycle


async def test_one_pr_drifting_8_adrs_files_one_batched_issue(
    loop_env, monkeypatch
) -> None:
    """#9662 — a single fleet PR drifting 8 ADRs (>= threshold 4) files ONE
    batched issue listing every affected ADR, not 8 per-ADR rollups."""
    cfg, state, pr, dedup, idx = loop_env
    # Add 8 ADRs each citing a distinct file the PR will touch.
    adr_dir = cfg.repo_root / "docs" / "adr"
    for i in range(8):
        _write_adr(
            adr_dir,
            number=100 + i,
            title=f"big{i}",
            related=[f"src/big{i}.py"],
        )
    from adr_index import ADRIndex  # noqa: PLC0415

    idx = ADRIndex(adr_dir)

    pr.create_issue = AsyncMock(return_value=200)

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8500,
                "mergedAt": "2026-05-07T20:00:00Z",
                "files": [{"path": f"src/big{i}.py"} for i in range(8)],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 1
    assert pr.create_issue.await_count == 1
    title = pr.create_issue.await_args.args[0]
    body = pr.create_issue.await_args.args[1]
    labels = pr.create_issue.await_args.args[2]
    assert "#8500" in title
    assert "8 ADRs" in title
    for i in range(8):
        assert f"ADR-{100 + i:04d}" in body
    # Adjusted close semantics are documented in the batched body (#9662).
    assert "NOT auto-closed" in body
    assert "hydraflow-adr-drift" in labels
    # State + dedup recorded under the FLEET-<pr> namespace, not ADR-NNNN.
    state.set_adr_rollup.assert_called_once()
    assert state.set_adr_rollup.call_args.args[0] == "FLEET-8500"
    assert state.set_adr_rollup.call_args.kwargs["pr_numbers"] == [8500]
    # #10457 — member ADR numbers persist so the resolver loop can triage
    # each one individually.
    assert state.set_adr_rollup.call_args.kwargs["adr_numbers"] == [
        100 + i for i in range(8)
    ]
    last_dedup = dedup.set_all.call_args.args[0]
    assert "adr_touchpoint_auditor:FLEET-8500" in last_dedup
    assert not any("ADR-01" in key for key in last_dedup)


async def test_below_threshold_pr_still_files_per_adr_rollups(
    loop_env, monkeypatch
) -> None:
    """#9662 — a PR drifting 3 ADRs (< threshold 4) keeps the per-ADR shape."""
    cfg, state, pr, dedup, idx = loop_env
    adr_dir = cfg.repo_root / "docs" / "adr"
    for i in range(3):
        _write_adr(
            adr_dir,
            number=100 + i,
            title=f"small{i}",
            related=[f"src/small{i}.py"],
        )
    from adr_index import ADRIndex  # noqa: PLC0415

    idx = ADRIndex(adr_dir)

    pr.create_issue = AsyncMock(side_effect=[201, 202, 203])

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8501,
                "mergedAt": "2026-05-07T20:00:00Z",
                "files": [{"path": f"src/small{i}.py"} for i in range(3)],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 3
    assert pr.create_issue.await_count == 3
    recorded_keys = [c.args[0] for c in state.set_adr_rollup.call_args_list]
    assert recorded_keys == ["ADR-0100", "ADR-0101", "ADR-0102"]
    assert not any(k.startswith("FLEET-") for k in recorded_keys)


async def test_three_prs_drifting_same_adr_file_one_rollup(
    loop_env, monkeypatch
) -> None:
    """3 PRs drifting the same ADR file ONE issue with all 3 PRs in body."""
    cfg, state, pr, dedup, idx = loop_env
    pr.create_issue = AsyncMock(return_value=555)

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8501,
                "mergedAt": "2026-05-07T10:00:00Z",
                "files": [{"path": "src/agent.py"}],
            },
            {
                "number": 8502,
                "mergedAt": "2026-05-07T11:00:00Z",
                "files": [{"path": "src/agent.py"}],
            },
            {
                "number": 8503,
                "mergedAt": "2026-05-07T12:00:00Z",
                "files": [{"path": "src/agent.py"}],
            },
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 1
    assert pr.create_issue.await_count == 1
    body = pr.create_issue.await_args.args[1]
    assert "#8501" in body
    assert "#8502" in body
    assert "#8503" in body
    # Rollup pr_numbers persisted to state.
    pr_numbers = state.set_adr_rollup.call_args.kwargs["pr_numbers"]
    assert sorted(pr_numbers) == [8501, 8502, 8503]


async def test_subsequent_tick_updates_body_with_new_prs(loop_env, monkeypatch) -> None:
    """Tick N+1 with a new PR drifting same ADR → update_issue_body, no new issue."""
    cfg, state, pr, dedup, idx = loop_env
    # Existing rollup state from a previous tick.
    state.get_adr_rollup.return_value = {
        "issue_number": 999,
        "pr_numbers": [8501],
    }

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8502,
                "mergedAt": "2026-05-07T22:00:00Z",
                "files": [{"path": "src/agent.py"}],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 0
    assert stats["updated"] == 1
    pr.create_issue.assert_not_awaited()
    pr.update_issue_body.assert_awaited_once()
    issue_number_arg, body_arg = pr.update_issue_body.await_args.args
    assert issue_number_arg == 999
    assert "#8501" in body_arg
    assert "#8502" in body_arg
    # State persists the merged PR set.
    merged = state.set_adr_rollup.call_args.kwargs["pr_numbers"]
    assert merged == [8501, 8502]


async def test_pr_gaining_adr_coverage_removed_from_rollup(
    loop_env, monkeypatch
) -> None:
    """A PR added in tick N, then ADR file updated in tick N+1 → rollup closed."""
    cfg, state, pr, dedup, idx = loop_env
    state.get_adr_rollup.return_value = {
        "issue_number": 999,
        "pr_numbers": [8501],
    }
    dedup.get.return_value = {"adr_touchpoint_auditor:ADR-0024"}

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8502,
                "mergedAt": "2026-05-07T22:00:00Z",
                "files": [
                    {"path": "src/agent.py"},
                    {"path": "docs/adr/0024-alpha.md"},
                ],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["closed"] == 1
    assert stats["filed"] == 0
    pr.close_issue.assert_awaited_once_with(999)
    state.clear_adr_rollup.assert_called_with("ADR-0024")
    state.clear_adr_audit_attempts.assert_called_with("ADR-0024")
    # Dedup key cleaned up.
    dedup.set_all.assert_called()
    last_set = dedup.set_all.call_args.args[0]
    assert "adr_touchpoint_auditor:ADR-0024" not in last_set


async def test_adr_file_in_diff_closes_rollup_no_new_issue(
    loop_env, monkeypatch
) -> None:
    """ADR's own file in diff and no open rollup → no issue filed, no close."""
    cfg, state, pr, dedup, idx = loop_env

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8474,
                "mergedAt": "2026-05-06T21:00:00Z",
                "files": [
                    {"path": "src/agent.py"},
                    {"path": "docs/adr/0024-alpha.md"},
                ],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()
    pr.close_issue.assert_not_awaited()


async def test_escalation_after_three_attempts(loop_env, monkeypatch) -> None:
    """3-strikes escalation triggers per-ADR rollup."""
    cfg, state, pr, dedup, idx = loop_env
    state.inc_adr_audit_attempts.return_value = 3

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8473,
                "mergedAt": "2026-05-06T20:00:00Z",
                "files": [{"path": "src/agent.py"}],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    assert stats["filed"] == 0
    labels = pr.create_issue.await_args.args[2]
    assert "hydraflow-hitl-escalation" in labels
    assert "hydraflow-adr-drift-stuck" in labels
    # The 3-strike attempt counter key is per ADR, not per (PR, ADR).
    state.inc_adr_audit_attempts.assert_called_with("ADR-0024")


async def test_escalation_does_not_storm_after_threshold(loop_env, monkeypatch) -> None:
    """Regression for the #8993 review finding: escalation fires exactly
    once when the per-ADR attempt counter crosses ``_MAX_ATTEMPTS`` (==3),
    not on every subsequent tick.

    Setup: an existing rollup (issue #4242) is open for ADR-0024, the
    attempt counter is now 4 (one tick after threshold). The loop should
    update the body and persist the new PR set, but it should NOT file a
    fresh HITL escalation issue.
    """
    cfg, state, pr, dedup, idx = loop_env
    # Tracked rollup exists with one prior PR; counter is past the threshold.
    state.get_adr_rollup.return_value = {
        "issue_number": 4242,
        "pr_numbers": [8473],
    }
    state.inc_adr_audit_attempts.return_value = 4

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8473,
                "mergedAt": "2026-05-06T20:00:00Z",
                "files": [{"path": "src/agent.py"}],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()

    # Existing rollup body was refreshed.
    assert pr.update_issue_body.await_count >= 1
    # And NO new escalation issue was filed — ``==`` not ``>=`` is the
    # whole point of this regression test.
    assert pr.create_issue.await_count == 0
    assert stats["escalated"] == 0


async def test_cursor_advances_to_most_recent_merged_at(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup, idx = loop_env

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 1,
                "mergedAt": "2026-05-06T20:00:00Z",
                "files": [{"path": "README.md"}],
            },
            {
                "number": 2,
                "mergedAt": "2026-05-06T22:00:00Z",
                "files": [{"path": "README.md"}],
            },
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    await loop._do_work()
    state.set_adr_audit_cursor.assert_called_with("2026-05-06T22:00:00Z")


async def test_kill_switch_short_circuits(loop_env) -> None:
    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "adr_touchpoint_auditor",
    )
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=deps,
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    loop._reconcile_closed_escalations.assert_not_awaited()
    pr.create_issue.assert_not_awaited()


async def test_close_reconcile_clears_dedup(loop_env, monkeypatch) -> None:
    """Closed adr-drift-stuck escalations clear their dedup key + attempt counter."""
    cfg, state, pr, dedup, idx = loop_env
    stuck_attempt_key = "ADR-0024"
    full_dedup_key = f"adr_touchpoint_auditor:{stuck_attempt_key}"
    current = {full_dedup_key, "adr_touchpoint_auditor:ADR-0042"}
    dedup.get.return_value = current

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    pr.list_closed_issues_by_label.return_value = [
        {
            "number": 9701,
            "title": f"HITL: ADR drift {stuck_attempt_key} unresolved after 3",
            "body": "",
            "updated_at": "",
        }
    ]

    def _no_subprocess(*_args, **_kwargs):
        raise AssertionError("reconcile must route through the PRPort, not raw gh")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_subprocess)

    await loop._reconcile_closed_escalations()

    pr.list_closed_issues_by_label.assert_awaited_once_with(
        cfg.adr_drift_stuck_label[0], limit=100
    )
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert full_dedup_key not in remaining
    assert "adr_touchpoint_auditor:ADR-0042" in remaining
    state.clear_adr_audit_attempts.assert_called_with(stuck_attempt_key)
    state.clear_adr_rollup.assert_called_with(stuck_attempt_key)


# --- #9554/#10028: gh subprocess sites route through run_subprocess_result ---


async def test_list_recent_merged_prs_routes_through_bounded_helper(
    loop_env, monkeypatch
) -> None:
    """Success path: parses gh pr list JSON via the shared helper."""
    from execution import SimpleResult

    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    captured: dict[str, Any] = {}

    async def fake_result(*cmd: str, **kwargs: Any) -> SimpleResult:
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return SimpleResult(
            stdout='[{"number": 1, "mergedAt": "2026-05-02T00:00:00Z"}]',
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(
        "adr_touchpoint_auditor_loop.run_subprocess_result", fake_result
    )

    prs = await loop._list_recent_merged_prs("2026-05-01T00:00:00Z")

    assert prs == [{"number": 1, "mergedAt": "2026-05-02T00:00:00Z"}]
    assert captured["cmd"][0] == "gh"
    assert captured["timeout"] == 120


async def test_list_recent_merged_prs_nonzero_returns_empty(
    loop_env, monkeypatch
) -> None:
    """Non-zero exit (never raised by the helper) yields an empty list."""
    from execution import SimpleResult

    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_result(*_cmd: str, **_kwargs: Any) -> SimpleResult:
        return SimpleResult(stdout="", stderr="rate limited", returncode=1)

    monkeypatch.setattr(
        "adr_touchpoint_auditor_loop.run_subprocess_result", fake_result
    )

    assert await loop._list_recent_merged_prs("2026-05-01T00:00:00Z") == []


async def test_list_recent_merged_prs_timeout_returns_empty(
    loop_env, monkeypatch
) -> None:
    """A timeout from the shared helper is caught locally and yields []."""
    from subprocess_util import SubprocessTimeoutError

    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_result(*_cmd: str, **_kwargs: Any) -> Any:
        raise SubprocessTimeoutError("timed out")

    monkeypatch.setattr(
        "adr_touchpoint_auditor_loop.run_subprocess_result", fake_result
    )

    assert await loop._list_recent_merged_prs("2026-05-01T00:00:00Z") == []


async def test_fetch_pr_changed_files_routes_through_bounded_helper(
    loop_env, monkeypatch
) -> None:
    from execution import SimpleResult

    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_result(*_cmd: str, **_kwargs: Any) -> SimpleResult:
        return SimpleResult(
            stdout='{"files": [{"path": "src/agent.py"}]}', stderr="", returncode=0
        )

    monkeypatch.setattr(
        "adr_touchpoint_auditor_loop.run_subprocess_result", fake_result
    )

    files = await loop._fetch_pr_changed_files(101)

    assert files == ["src/agent.py"]


# --- #9662: fleet-batch guards, namespaces, and close/dedup semantics ---


def _fleet_env(monkeypatch, loop, *, pr_number=8500):
    """Wire a fleet PR (8 drifting ADRs, >= threshold 4) into *loop*."""

    async def fake_list(_cursor):
        return [
            {
                "number": pr_number,
                "mergedAt": "2026-05-07T20:00:00Z",
                "files": [{"path": f"src/big{i}.py"} for i in range(8)],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())


def _fleet_index(cfg):
    from adr_index import ADRIndex  # noqa: PLC0415

    adr_dir = cfg.repo_root / "docs" / "adr"
    for i in range(8):
        _write_adr(adr_dir, number=100 + i, title=f"big{i}", related=[f"src/big{i}.py"])
    return ADRIndex(adr_dir)


async def test_fleet_batch_not_refiled_when_state_tracked(
    loop_env, monkeypatch
) -> None:
    """Re-scan with the fleet rollup already tracked in state → no re-file."""
    cfg, state, pr, dedup, idx = loop_env
    idx = _fleet_index(cfg)
    state.get_adr_rollup.side_effect = lambda key: (
        {"issue_number": 777, "pr_numbers": [8500]} if key == "FLEET-8500" else None
    )

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    _fleet_env(monkeypatch, loop)
    monkeypatch.setattr(loop, "_reconcile_stale_rollups", AsyncMock(return_value=0))

    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()
    state.set_adr_rollup.assert_not_called()


async def test_fleet_batch_not_refiled_when_dedup_key_present(
    loop_env, monkeypatch
) -> None:
    """Dedup key present but state cleared → skip until reconcile catches up."""
    cfg, state, pr, dedup, idx = loop_env
    idx = _fleet_index(cfg)
    dedup.get.return_value = {"adr_touchpoint_auditor:FLEET-8500"}

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    _fleet_env(monkeypatch, loop)

    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()
    state.set_adr_rollup.assert_not_called()


async def test_fleet_zero_sentinel_does_not_record_or_dedup(
    loop_env, monkeypatch
) -> None:
    """create_issue's 0 sentinel on a fleet batch records neither state nor
    dedup — the next tick retries (same contract as per-ADR rollups)."""
    cfg, state, pr, dedup, idx = loop_env
    idx = _fleet_index(cfg)
    pr.create_issue = AsyncMock(return_value=0)

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    _fleet_env(monkeypatch, loop)

    stats = await loop._do_work()
    pr.create_issue.assert_awaited()  # it tried
    assert stats["filed"] == 0
    state.set_adr_rollup.assert_not_called()
    dedup.set_all.assert_not_called()


async def test_fleet_and_per_adr_namespaces_never_collide(
    loop_env, monkeypatch
) -> None:
    """A per-ADR dedup key for ADR 8500 must not suppress the fleet batch for
    PR 8500 (FLEET-<pr> vs ADR-NNNN are disjoint sub-namespaces)."""
    cfg, state, pr, dedup, idx = loop_env
    idx = _fleet_index(cfg)
    # Same numeral in the per-ADR namespace — must not alias FLEET-8500.
    dedup.get.return_value = {"adr_touchpoint_auditor:ADR-8500"}

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    _fleet_env(monkeypatch, loop)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    assert state.set_adr_rollup.call_args.args[0] == "FLEET-8500"
    last_dedup = dedup.set_all.call_args.args[0]
    assert "adr_touchpoint_auditor:FLEET-8500" in last_dedup
    assert "adr_touchpoint_auditor:ADR-8500" in last_dedup  # untouched


async def test_manually_closed_fleet_rollup_state_cleared(loop_env) -> None:
    """#9662 close semantics: a human-closed batched issue clears the
    FLEET-<pr> state, attempt counter, and dedup key via the stale-rollup
    reconcile pass — nothing strands, and re-detection could re-file."""
    cfg, state, pr, dedup, idx = loop_env
    state.all_adr_rollups.return_value = {
        "FLEET-9592": {"issue_number": 777, "pr_numbers": [9592]},
    }
    dedup.get.return_value = {"adr_touchpoint_auditor:FLEET-9592"}
    pr.get_issue_state = AsyncMock(return_value="COMPLETED")

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    closed = await loop._reconcile_stale_rollups(
        drifting_adrs=set(), adrs_resolved_this_tick=set()
    )
    assert closed == 1
    state.clear_adr_rollup.assert_called_with("FLEET-9592")
    state.clear_adr_audit_attempts.assert_called_with("FLEET-9592")
    remaining = dedup.set_all.call_args.args[0]
    assert "adr_touchpoint_auditor:FLEET-9592" not in remaining


async def test_open_fleet_rollup_left_alone_by_stale_reconcile(loop_env) -> None:
    """One-shot semantics: an OPEN batched issue is never auto-closed by the
    stale-rollup recompute path (no drift recompute for fleet keys)."""
    cfg, state, pr, dedup, idx = loop_env
    state.all_adr_rollups.return_value = {
        "FLEET-9592": {"issue_number": 777, "pr_numbers": [9592]},
    }
    pr.get_issue_state = AsyncMock(return_value="OPEN")
    fetch = AsyncMock(return_value=[])

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    loop._fetch_pr_changed_files = fetch  # type: ignore[method-assign]

    closed = await loop._reconcile_stale_rollups(
        drifting_adrs=set(), adrs_resolved_this_tick=set()
    )
    assert closed == 0
    pr.close_issue.assert_not_awaited()
    state.clear_adr_rollup.assert_not_called()
    # No drift recompute over the fleet PR — one-shot by design.
    fetch.assert_not_awaited()


async def test_closed_fleet_escalation_clears_dedup_and_state(loop_env) -> None:
    """The shared escalation reconciler handles FLEET-<pr> subjects: closing
    a fleet escalation clears its dedup key, attempts, and rollup state."""
    cfg, state, pr, dedup, idx = loop_env
    full_dedup_key = "adr_touchpoint_auditor:FLEET-9592"
    dedup.get.return_value = {full_dedup_key, "adr_touchpoint_auditor:ADR-0042"}

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    pr.list_closed_issues_by_label.return_value = [
        {
            "number": 9701,
            "title": "HITL: ADR drift FLEET-9592 unresolved after 3",
            "body": "",
            "updated_at": "",
        }
    ]

    await loop._reconcile_closed_escalations()

    remaining = dedup.set_all.call_args.args[0]
    assert full_dedup_key not in remaining
    assert "adr_touchpoint_auditor:ADR-0042" in remaining
    state.clear_adr_audit_attempts.assert_called_with("FLEET-9592")
    state.clear_adr_rollup.assert_called_with("FLEET-9592")


# --- #10456: churn-derived shared-infra suppression threaded to both sites ---


async def test_main_scan_suppresses_high_fanout_bare_cited_module(
    loop_env, monkeypatch, tmp_path
) -> None:
    """#10456: the main scan threads ``adr_drift_shared_infra_fanout_threshold``
    to ``partition_fleet_drift`` — a module bare-cited by >= threshold live ADRs
    files NO rollup, with no ``_SHARED_INFRA_MODULES`` edit. Without the
    threading these >= threshold bare citations would file a fleet batch."""
    cfg, state, pr, dedup, _idx = loop_env
    threshold = cfg.adr_drift_shared_infra_fanout_threshold
    adr_dir = tmp_path / "fanout" / "adr"
    adr_dir.mkdir(parents=True)
    for i in range(threshold):
        _write_adr(adr_dir, number=600 + i, title=f"hot{i}", related=["src/hot.py"])
    from adr_index import ADRIndex  # noqa: PLC0415

    idx = ADRIndex(adr_dir)

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8888,
                "mergedAt": "2026-05-06T20:00:00Z",
                "title": "feat: churn the hot module",
                "files": [{"path": "src/hot.py"}],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()
    state.set_adr_rollup.assert_not_called()


async def test_reconcile_autocloses_rollup_obsoleted_by_fanout(
    loop_env, tmp_path
) -> None:
    """#10456: the stale-rollup reconcile threads the same threshold to
    ``compute_drift_by_adr`` — an OPEN per-ADR rollup whose recompute is now
    empty under fan-out suppression auto-closes. Without the threading the ADR
    would still drift and the rollup would strand open."""
    cfg, state, pr, dedup, _idx = loop_env
    threshold = cfg.adr_drift_shared_infra_fanout_threshold
    adr_dir = tmp_path / "fanout" / "adr"
    adr_dir.mkdir(parents=True)
    for i in range(threshold):
        _write_adr(adr_dir, number=600 + i, title=f"hot{i}", related=["src/hot.py"])
    from adr_index import ADRIndex  # noqa: PLC0415

    idx = ADRIndex(adr_dir)

    state.all_adr_rollups.return_value = {
        "ADR-0600": {"issue_number": 555, "pr_numbers": [123]},
    }
    pr.get_issue_state = AsyncMock(return_value="OPEN")

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    loop._fetch_pr_changed_files = AsyncMock(  # type: ignore[method-assign]
        return_value=["src/hot.py"]
    )

    closed = await loop._reconcile_stale_rollups(
        drifting_adrs=set(), adrs_resolved_this_tick=set()
    )
    assert closed == 1
    state.clear_adr_rollup.assert_called_with("ADR-0600")
    pr.close_issue.assert_awaited_with(555)


# --- #9662 P5: ADR-0056 amendment stays self-covered and in sync ---


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_landing_pr_shape_does_not_drift_adr_0056() -> None:
    """Self-coverage: a diff shaped like the #9662 landing PR (adr_drift +
    the amended ADR-0056 file) yields zero drift findings for ADR-0056."""
    from adr_drift import compute_drift  # noqa: PLC0415
    from adr_index import ADRIndex  # noqa: PLC0415

    idx = ADRIndex(_repo_root() / "docs" / "adr")
    findings = compute_drift(
        idx,
        pr_number=9662,
        changed_files=[
            "src/adr_drift.py",
            "src/adr_touchpoint_auditor_loop.py",
            "src/config.py",
            "docs/adr/0056-adr-touchpoint-gate-to-caretaker-loop.md",
        ],
    )
    assert 56 not in {f.adr.number for f in findings}


def test_adr_0056_enforced_by_line_intact() -> None:
    """The amendment must not disturb the `**Enforced by:**` conformance line."""
    text = (
        _repo_root() / "docs" / "adr" / "0056-adr-touchpoint-gate-to-caretaker-loop.md"
    ).read_text()
    assert "**Enforced by:** pytest:tests/test_adr_touchpoint_auditor_loop.py" in text


def test_adr_0056_amendment_matches_config_knob() -> None:
    """Doc↔config parity: the amended ADR names the knob and its default,
    matching the live `HydraFlowConfig` Field."""
    text = (
        _repo_root() / "docs" / "adr" / "0056-adr-touchpoint-gate-to-caretaker-loop.md"
    ).read_text()
    assert "adr_drift_fleet_batch_threshold" in text
    assert "default 4" in text
    cfg = HydraFlowConfig()
    assert cfg.adr_drift_fleet_batch_threshold == 4
    # The amendment cites the new pure symbols so ADR-0056 stays self-covered.
    assert "partition_fleet_drift" in text
    assert "FleetDriftBatch" in text
