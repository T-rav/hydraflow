"""Regression guard for #10225 — AdrConformanceLoop froze the event loop.

Root cause: ``AdrConformanceLoop._do_work`` (async) called
``adr_conformance.evaluate_adrs`` SYNCHRONOUSLY on the asyncio event-loop
thread. ``evaluate_adrs`` runs every Accepted ADR's ``**Enforced by:**`` check
as a BLOCKING ``subprocess.run`` (pytest/make, ``timeout_s=300``;
``SubprocessConformanceRunner.run``). A single check wedged the single event
loop for the whole sweep, tripping the 120s event-loop freeze detector
(``event_loop_watchdog.py``) and — with ``hard_restart=False`` — taking the
entire factory (dashboard + every loop) down. Observed live: the factory
froze ~2 min after every startup.

Fix: offload the sweep via ``asyncio.to_thread`` so it runs OFF the loop
thread. This guard asserts that behaviorally — ``evaluate_adrs`` must be
invoked on a thread other than the event-loop thread. Without the fix (an
inline call) it runs on the loop thread and this test fails.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import adr_conformance
from adr_conformance import CheckOutcome
from adr_conformance_loop import AdrConformanceLoop
from adr_index import ADRIndex
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from mockworld.fakes import FakeConformanceRunner
from state import StateTracker


class _PRStub:
    """Minimal async PRManager: a PASS sweep files nothing, so these are no-ops."""

    async def create_issue(self, *args: Any, **kwargs: Any) -> int:
        return 100

    async def update_issue_body(self, *args: Any, **kwargs: Any) -> None: ...

    async def close_issue(self, *args: Any, **kwargs: Any) -> None: ...

    async def list_closed_issues_by_label(self, *args: Any, **kwargs: Any) -> list:
        return []


def _build_loop(tmp_path: Path) -> AdrConformanceLoop:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0049-fixture.md").write_text(
        "# ADR-0049: Fixture\n\n"
        "**Status:** Accepted\n**Date:** 2026-01-01\n"
        "**Enforcement:** enforced\n**Enforced by:** make:conformance-fixture\n\n"
        "## Context\n\nBody.\n"
    )
    (tmp_path / "Makefile").write_text("conformance-fixture:\n\techo hi\n")
    cfg = HydraFlowConfig(
        data_root=tmp_path / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=tmp_path,
        adr_conformance_loop_enabled=True,
    )
    pr_manager: Any = _PRStub()
    return AdrConformanceLoop(
        config=cfg,
        state=StateTracker(tmp_path / ".hydraflow" / "state.json"),
        pr_manager=pr_manager,
        dedup=DedupStore("adr_conformance", tmp_path / ".hydraflow" / "dedup.json"),
        adr_index=ADRIndex(adr_dir),
        runner=FakeConformanceRunner({"make:conformance-fixture": CheckOutcome.PASS}),
        deps=LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=lambda *a, **k: None,
            enabled_cb=lambda _n: True,
        ),
    )


async def test_do_work_offloads_evaluate_adrs_off_event_loop_thread(
    tmp_path, monkeypatch
) -> None:
    """#10225: the blocking ADR-conformance sweep must run OFF the event-loop
    thread (via ``asyncio.to_thread``) so a slow subprocess check can never
    wedge the single asyncio loop and freeze the whole factory."""
    loop = _build_loop(tmp_path)
    loop_thread = threading.current_thread()
    seen: dict[str, threading.Thread] = {}
    real_evaluate = adr_conformance.evaluate_adrs

    def _spy(*args, **kwargs):
        seen["thread"] = threading.current_thread()
        return real_evaluate(*args, **kwargs)

    # _do_work does a local ``from adr_conformance import evaluate_adrs``, so
    # patching the module attribute is picked up on the next call.
    monkeypatch.setattr(adr_conformance, "evaluate_adrs", _spy)
    await loop._do_work()

    assert "thread" in seen, "evaluate_adrs was never invoked by _do_work"
    assert seen["thread"] is not loop_thread, (
        "evaluate_adrs ran on the event-loop thread — it must be offloaded via "
        "asyncio.to_thread so a blocking subprocess sweep cannot freeze the "
        "factory (#10225)"
    )
