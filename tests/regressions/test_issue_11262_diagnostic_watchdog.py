"""Regression for #11262: DiagnosticLoop crash-looped on the watchdog.

DiagnosticLoop spawns a two-stage (diagnose + fix) LLM subprocess per queued
``hydraflow-diagnose`` issue, serially, inside one watchdog-bounded
``_do_work()`` cycle -- but never set ``LONG_LLM_CYCLE = True`` (unlike every
sibling loop that spawns LLM work: disturbance_dampener_loop,
goal_supervisor_loop, intervention_tally_loop, sampled_audit_loop,
issue_refinement_loop, report_issue_loop). It therefore inherited the tight
``loop_watchdog_default_seconds`` (2h) bound instead of the wide
``loop_watchdog_llm_seconds`` (4h) one. With a deep hydraflow-diagnose
backlog queued, the cycle overran the tight bound, ``LoopCycleTimeoutError``
fired, and the persistent-error actuator recorded 24 consecutive ``error``
heartbeats it could not explain (``details={}``, "none registered for this
loop").

Fix: ``DiagnosticLoop.LONG_LLM_CYCLE = True``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from diagnostic_loop import DiagnosticLoop
from events import EventBus, EventType
from tests.helpers import ConfigFactory


def _make_loop(tmp_path: Path) -> DiagnosticLoop:
    """Build a real DiagnosticLoop wired to a real config and event bus."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    object.__setattr__(config, "diagnostic_loop_enabled", True)

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _name: True,
    )

    runner = MagicMock()
    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    state = MagicMock()

    return DiagnosticLoop(config=config, runner=runner, prs=prs, state=state, deps=deps)


def test_diagnostic_loop_opts_into_the_llm_watchdog_bound() -> None:
    """DiagnosticLoop declares LONG_LLM_CYCLE, mirroring every sibling loop
    that spawns an LLM subprocess per cycle."""
    assert DiagnosticLoop.LONG_LLM_CYCLE is True, (
        "DiagnosticLoop spawns a two-stage diagnose+fix LLM subprocess per "
        "queued issue, serially, inside one _do_work() cycle -- it must opt "
        "into the wider loop_watchdog_llm_seconds bound like every sibling "
        "LLM-spawning loop, or a deep hydraflow-diagnose backlog overruns "
        "the tight default watchdog and crash-loops (#11262)."
    )


def test_cycle_timeout_resolves_to_the_llm_bound_not_the_default(
    tmp_path: Path,
) -> None:
    """_cycle_timeout_seconds() resolves to loop_watchdog_llm_seconds (4h),
    not loop_watchdog_default_seconds (2h)."""
    loop = _make_loop(tmp_path)

    assert loop._config.loop_watchdog_llm_seconds == 14400
    assert loop._cycle_timeout_seconds() == 14400
    assert loop._cycle_timeout_seconds() != loop._config.loop_watchdog_default_seconds


@pytest.mark.asyncio
async def test_multi_issue_cycle_survives_a_bound_the_tight_default_would_miss(
    tmp_path: Path,
) -> None:
    """A cycle that legitimately runs longer than the tight default bound
    still completes, because DiagnosticLoop resolves to the wider LLM bound
    instead of the default one.

    Scales both watchdog bounds down (rather than sleeping for real hours)
    to exercise "the cycle exceeds loop_watchdog_default_seconds but fits
    inside loop_watchdog_llm_seconds" -- the exact shape of the production
    incident (17 queued issues processed serially overran the 2h default) --
    in test time. Because the assertion reads the SAME resolution path
    (``_cycle_timeout_seconds`` -> ``LONG_LLM_CYCLE``) production uses, this
    test regresses if ``LONG_LLM_CYCLE`` is ever removed from DiagnosticLoop.
    """
    loop = _make_loop(tmp_path)
    object.__setattr__(loop._config, "loop_watchdog_default_seconds", 0.05)
    object.__setattr__(loop._config, "loop_watchdog_llm_seconds", 1.0)

    async def slow_multi_issue_cycle() -> dict[str, Any]:
        # Stands in for N issues' diagnose+fix subprocesses run serially:
        # longer than the (scaled) tight default, well inside the (scaled)
        # LLM bound.
        await asyncio.sleep(0.2)
        return {"processed": 3, "fixed": 2, "escalated": 1, "retried": 0}

    loop._do_work = slow_multi_issue_cycle  # type: ignore[method-assign]

    assert loop._cycle_timeout_seconds() == 1.0

    await asyncio.wait_for(loop._execute_cycle(), timeout=5)

    status_events = [
        e for e in loop._bus.get_history() if e.type == EventType.BACKGROUND_WORKER_STATUS
    ]
    assert status_events, "no BACKGROUND_WORKER_STATUS published"
    assert status_events[-1].data["status"] == "ok", (
        "cycle should have completed under the wide LLM bound, not been "
        f"cancelled by the watchdog: {status_events[-1].data}"
    )

    error_events = [e for e in loop._bus.get_history() if e.type == EventType.ERROR]
    assert not error_events, f"watchdog fired when it should not have: {error_events}"
