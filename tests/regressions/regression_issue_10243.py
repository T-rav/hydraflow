"""Regression guard for #10243 — ADR conformance false-positive storm, part 2.

Companion to ``regression_issue_10211.py``. #10212 fixed the *trigger* of the
storm (bare ``python`` → ``sys.executable``) but left the failure mode live: if
``sys.executable``'s own venv is missing pytest (a half-synced factory venv
where the test extra was dropped — ``uv sync`` without ``--all-extras``), every
pytest-kind conformance check still fails identically with "No module named
pytest", which ``SubprocessConformanceRunner.run`` maps to FAIL — storming one
false-positive drift issue per enforced ADR (#10182–#10195).

The fix keeps #10212's per-check FAIL semantics intact and adds a loop-level
pre-flight: ``AdrConformanceLoop`` probes ``runner.available()`` once per tick
and, when pytest can't launch, skips the whole tick and files NOTHING — raising
a single operational alert instead of a per-ADR issue storm.

This guard asserts the loop's short-circuit: given an unavailable runner, no
issue is ever filed and the tick reports ``runner_env_unavailable``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from adr_conformance import CheckOutcome
from adr_conformance_loop import AdrConformanceLoop
from adr_index import ADRIndex
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from mockworld.fakes import FakeConformanceRunner
from state import StateTracker


def _build_loop(tmp_path: Path, *, available: bool):
    repo_root = tmp_path
    (repo_root / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    cfg = HydraFlowConfig(
        data_root=repo_root / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=repo_root,
        adr_conformance_loop_enabled=True,
    )
    pr = AsyncMock()
    loop = AdrConformanceLoop(
        config=cfg,
        state=StateTracker(repo_root / ".hydraflow" / "state.json"),
        pr_manager=pr,
        dedup=DedupStore("adr_conformance", repo_root / ".hydraflow" / "dedup.json"),
        adr_index=ADRIndex(repo_root / "docs" / "adr"),
        runner=FakeConformanceRunner(
            {"make:x": CheckOutcome.FAIL}, available=available
        ),
        deps=LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=lambda *a, **k: None,
            enabled_cb=lambda _name: True,
        ),
    )
    return loop, pr


async def test_unavailable_runner_skips_tick_and_files_no_drift_issue(tmp_path):
    """#10243: a broken runner env (pytest not importable) must skip the whole
    tick and file NOTHING — never storm one false-positive drift issue per ADR."""
    loop, pr = _build_loop(tmp_path, available=False)

    result = await loop._do_work()

    assert result == {"status": "runner_env_unavailable"}
    pr.create_issue.assert_not_called()
