"""Regression for issue #9622.

`AdrTouchpointAuditorLoop` stranded open rollups when a module was later
added to ``_SHARED_INFRA_MODULES`` (or an ADR's citations otherwise became
obsolete). ``compute_drift_by_adr`` only scans PRs merged since the cursor,
so the *old* PRs that originally drifted the ADR (before the cursor) were
never rescanned: drift recomputed empty, the tracked rollup could neither
update nor auto-close, and it stranded open forever. ``_reconcile_closed_
escalations`` only cleared state for escalation-labeled closes, so a
manually-closed non-escalated rollup orphaned its state too.

Fix: a stale-rollup reconciliation pass runs each tick. For every tracked
rollup whose ADR is NOT drifting in this tick's window (and not resolved by
an ADR-file touch), the loop re-fetches the rollup's OWN tracked PR diffs
by stored ``pr_number`` and recomputes drift over JUST those PRs. Empty ⇒
the rollup is obsolete ⇒ close + clear state/attempts/dedup atomically.
A manually-closed rollup issue is likewise reconciled.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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


def _build_loop(tmp_path: Path, *, rollups: dict, dedup_keys: set):
    """Build a loop whose ADR-0038 cites a now-shared-infra module.

    ``src/dashboard.py`` is in ``adr_drift._SHARED_INFRA_MODULES`` — a bare
    citation of it no longer drifts, so a rollup filed for ADR-0038 before
    the module was exempted is now obsolete.
    """
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    # ADR-0038 cites ONLY a shared-infra module -> its old rollup is obsolete.
    _write_adr(adr_dir, number=38, title="dash", related=["src/dashboard.py"])

    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
        # Loop now defaults OFF (#10540); force ON for this regression pin.
        adr_touchpoint_auditor_loop_enabled=True,
    )

    state = MagicMock()
    state.get_adr_audit_cursor.return_value = "2026-06-01T00:00:00+00:00"
    state.get_adr_audit_attempts.return_value = 0
    state.inc_adr_audit_attempts.return_value = 1
    state.get_adr_rollup.return_value = None
    state.all_adr_rollups.return_value = rollups

    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.update_issue_body = AsyncMock(return_value=None)
    pr.close_issue = AsyncMock(return_value=None)
    pr.get_issue_state = AsyncMock(return_value="OPEN")

    dedup = MagicMock()
    dedup.get.return_value = set(dedup_keys)

    from adr_index import ADRIndex  # noqa: PLC0415

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=ADRIndex(adr_dir),
        deps=_deps(stop),
    )
    return loop, state, pr, dedup


async def _unrelated_window_pr(_cursor):
    """A PR merged this tick that does NOT drift ADR-0038 (docs-only)."""
    return [
        {
            "number": 9700,
            "mergedAt": "2026-06-02T10:00:00Z",
            "files": [{"path": "README.md"}],
        }
    ]


async def test_stale_rollup_on_shared_infra_addition_is_auto_closed(
    tmp_path, monkeypatch
) -> None:
    """The core #9622 bug: a rollup whose sole contributor module is now
    shared-infra is auto-closed and its state cleared on the next tick."""
    loop, state, pr, dedup = _build_loop(
        tmp_path,
        rollups={"ADR-0038": {"issue_number": 9418, "pr_numbers": [9100]}},
        dedup_keys={"adr_touchpoint_auditor:ADR-0038"},
    )

    # The rollup's OWN tracked PR (#9100) touched only src/dashboard.py, which
    # is now shared-infra -> recompute drift over JUST it yields empty.
    async def fake_fetch(pr_number: int):
        assert pr_number == 9100  # recompute over OWN PR, not this tick's window
        return ["src/dashboard.py"]

    monkeypatch.setattr(loop, "_fetch_pr_changed_files", fake_fetch)
    monkeypatch.setattr(loop, "_list_recent_merged_prs", _unrelated_window_pr)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()

    assert stats["closed"] >= 1
    pr.close_issue.assert_awaited_once_with(9418)
    state.clear_adr_rollup.assert_called_with("ADR-0038")
    state.clear_adr_audit_attempts.assert_called_with("ADR-0038")
    dedup.set_all.assert_called()
    last_set = dedup.set_all.call_args.args[0]
    assert "adr_touchpoint_auditor:ADR-0038" not in last_set


async def test_stale_rollup_still_drifting_is_not_closed(tmp_path, monkeypatch) -> None:
    """CRITICAL guard: recompute is scoped to the rollup's OWN PRs. If those
    PRs still genuinely drift the ADR, the rollup is NOT closed on a quiet
    tick (otherwise every rollup would be wrongly closed)."""
    loop, state, pr, dedup = _build_loop(
        tmp_path,
        rollups={"ADR-0038": {"issue_number": 9418, "pr_numbers": [9100]}},
        dedup_keys={"adr_touchpoint_auditor:ADR-0038"},
    )

    # Re-point ADR-0038 at a non-shared-infra file so its drift persists.
    # (mtime change forces ADRIndex to re-scan on next access.)
    adr_dir = tmp_path / "docs" / "adr"
    (adr_dir / "0038-dash.md").write_text(
        "# ADR-0038: dash\n\n- **Status:** Accepted\n- **Date:** 2026-01-01\n"
        "- **Related:** `src/agent.py`\n\n## Context\n\nx\n"
    )

    # #9100 still touches the cited (non-shared-infra) file -> still drifts.
    async def fetch_agent(pr_number: int):
        return ["src/agent.py"]

    monkeypatch.setattr(loop, "_fetch_pr_changed_files", fetch_agent)
    monkeypatch.setattr(loop, "_list_recent_merged_prs", _unrelated_window_pr)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()

    assert stats["closed"] == 0
    pr.close_issue.assert_not_awaited()
    state.clear_adr_rollup.assert_not_called()


async def test_manually_closed_non_escalated_rollup_state_cleared(
    tmp_path, monkeypatch
) -> None:
    """A rollup issue closed by a human (non-escalated) orphans its state
    because ``_reconcile_closed_escalations`` never sees it. The stale-rollup
    pass detects the closed issue and clears the orphaned state."""
    loop, state, pr, dedup = _build_loop(
        tmp_path,
        rollups={"ADR-0038": {"issue_number": 9418, "pr_numbers": [9100]}},
        dedup_keys={"adr_touchpoint_auditor:ADR-0038"},
    )
    # Human closed the rollup as won't-fix / resolved.
    pr.get_issue_state = AsyncMock(return_value="NOT_PLANNED")

    # Even though the PR would still drift, a manual close must clear state.
    async def fetch_still_drifts(pr_number: int):
        return ["src/agent.py"]

    monkeypatch.setattr(loop, "_fetch_pr_changed_files", fetch_still_drifts)
    monkeypatch.setattr(loop, "_list_recent_merged_prs", _unrelated_window_pr)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()

    assert stats["closed"] >= 1
    state.clear_adr_rollup.assert_called_with("ADR-0038")
    state.clear_adr_audit_attempts.assert_called_with("ADR-0038")
