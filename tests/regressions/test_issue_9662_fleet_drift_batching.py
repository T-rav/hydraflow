"""Regression for issue #9662.

A cross-cutting caretaker-fleet hardening PR (#9592 added the bounded
subprocess read across 9 owned loops) touched N owned-loop modules at
once, each bare-cited by exactly one ADR and correctly NOT in
``_SHARED_INFRA_MODULES``. ``AdrTouchpointAuditorLoop`` then amplified
that single PR into N near-identical per-ADR drift rollups (#9603 for
ADR-0048, #9606 for ADR-0089), drowning the grooming/HITL queue in issues
sharing one root cause.

Fix (batching heuristic, per the ratified plan — NOT a revived
``Skip-ADR:`` marker, which would contradict ADR-0056 Rule 4): when one PR
drifts >= ``adr_drift_fleet_batch_threshold`` distinct ADRs,
``partition_fleet_drift`` collapses them into one ``FleetDriftBatch`` and
the loop files ONE batched ``hydraflow-adr-drift`` issue (dedup key
``adr_touchpoint_auditor:FLEET-<pr>``). Closing the batched issue clears
ALL of its tracking (state, attempts, dedup) in one pass — no per-ADR keys
are ever created for a batched PR, so re-detection cannot re-file per-ADR.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from adr_drift import partition_fleet_drift
from adr_index import ADRIndex
from adr_touchpoint_auditor_loop import AdrTouchpointAuditorLoop
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus

_FLEET_PR = 9592
_LOOP_COUNT = 9  # the #9592 sweep touched 9 caretaker loops


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _write_adr(adr_dir: Path, *, number: int, related: str) -> None:
    body = (
        f"# ADR-{number:04d}: owns loop{number}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** `{related}`\n\n"
        f"## Context\n\nFixture body.\n"
    )
    (adr_dir / f"{number:04d}-loop{number}.md").write_text(body)


def _fleet_fixture(tmp_path: Path) -> tuple[ADRIndex, list[str]]:
    """Nine owned-loop ADRs, one module each — the #9592 shape."""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    files = []
    for i in range(_LOOP_COUNT):
        module = f"src/caretaker_loop_{i}.py"
        _write_adr(adr_dir, number=200 + i, related=module)
        files.append(module)
    return ADRIndex(adr_dir), files


def test_one_fleet_pr_is_one_batch_not_nine_rollups(tmp_path: Path) -> None:
    """Pure pin: the #9592 shape partitions to ONE batch, zero per-ADR."""
    index, files = _fleet_fixture(tmp_path)
    per_adr, batches = partition_fleet_drift(
        index, [(_FLEET_PR, files)], fleet_threshold=4
    )
    assert per_adr == []  # no double-filing — the amplification is gone
    assert len(batches) == 1
    assert batches[0].pr_number == _FLEET_PR
    assert len(batches[0].adr_numbers) == _LOOP_COUNT


async def test_loop_files_one_batched_issue_for_fleet_pr(tmp_path: Path) -> None:
    """Loop pin: the observed #9592 → #9603/#9606 amplification now files
    exactly ONE issue, tracked under the FLEET-<pr> namespace."""
    index, files = _fleet_fixture(tmp_path)
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
        # Loop now defaults OFF (#10540); force ON for this fleet-batch pin.
        adr_touchpoint_auditor_loop_enabled=True,
    )
    state = MagicMock()
    state.get_adr_audit_cursor.return_value = "2026-07-01T00:00:00Z"
    state.inc_adr_audit_attempts.return_value = 1
    state.get_adr_rollup.return_value = None
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=4242)
    dedup = MagicMock()
    dedup.get.return_value = set()

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=index,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": _FLEET_PR,
                "mergedAt": "2026-07-11T10:00:00Z",
                "files": [{"path": p} for p in files],
            }
        ]

    loop._list_recent_merged_prs = fake_list  # type: ignore[method-assign]
    loop._reconcile_closed_escalations = AsyncMock()  # type: ignore[method-assign]

    stats = await loop._do_work()

    assert stats["filed"] == 1
    assert pr.create_issue.await_count == 1
    state.set_adr_rollup.assert_called_once()
    assert state.set_adr_rollup.call_args.args[0] == f"FLEET-{_FLEET_PR}"
    # No per-ADR dedup keys for a batched PR — closing the batch clears its
    # single FLEET key and nothing can re-file per-ADR from the same scan.
    last_dedup = dedup.set_all.call_args.args[0]
    assert last_dedup == {f"adr_touchpoint_auditor:FLEET-{_FLEET_PR}"}


async def test_closing_batched_issue_clears_all_tracking(tmp_path: Path) -> None:
    """Close pin: a human-closed batched issue clears state + attempts + the
    FLEET dedup key in one reconcile pass (the renumber/right-size-first
    lesson: close must clear ALL of the batch's keys or re-detection
    re-files)."""
    index, _files = _fleet_fixture(tmp_path)
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
        # Loop now defaults OFF (#10540); force ON for this fleet-batch pin.
        adr_touchpoint_auditor_loop_enabled=True,
    )
    fleet_key = f"FLEET-{_FLEET_PR}"
    state = MagicMock()
    state.all_adr_rollups.return_value = {
        fleet_key: {"issue_number": 4242, "pr_numbers": [_FLEET_PR]},
    }
    pr = AsyncMock()
    pr.get_issue_state = AsyncMock(return_value="COMPLETED")
    dedup = MagicMock()
    dedup.get.return_value = {f"adr_touchpoint_auditor:{fleet_key}"}

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=index,
        deps=_deps(stop),
    )

    closed = await loop._reconcile_stale_rollups(
        drifting_adrs=set(), adrs_resolved_this_tick=set()
    )

    assert closed == 1
    state.clear_adr_rollup.assert_called_with(fleet_key)
    state.clear_adr_audit_attempts.assert_called_with(fleet_key)
    remaining = dedup.set_all.call_args.args[0]
    assert f"adr_touchpoint_auditor:{fleet_key}" not in remaining
