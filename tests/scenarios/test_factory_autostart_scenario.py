"""MockWorld scenario: boot-time factory autostart end-to-end (#11208).

Covers the spec's two required scenarios with a REAL ``RepoRuntime`` wired to
MockWorld's air-gapped Fakes exactly the way the dashboard's Start button
wires one (``MockWorld._build_wired_orchestrator`` — see the #10253
regression test, ``tests/regressions/test_issue_10253_airgap_start_orchestrator.py``,
for the precedent this mirrors):

1. boot -> autostart -> working: ``maybe_autostart_host`` — the same call
   ``server.py``'s boot sequence makes — actually starts the host line, and
   the real background loop fleet triages a seeded issue. Asserting on the
   FakeGitHub label transition (not a mocked call) proves autostart produced
   genuine work, not just a flipped ``running`` flag.
2. boot-during-credit-pause -> paused: credits are already exhausted the
   moment the first ``plan()`` call fires (``FakeLLM.script_plan_credit_
   exhaustion``, the same one-shot ``CreditExhaustedError`` mechanism
   ``tests/test_credit_pause.py`` uses). Autostart must boot INTO the pause
   via the orchestrator's own real credit-exhaustion detection — asserted via
   ``orch.credits_paused_until`` becoming non-None, not a mocked assertion.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from factory_autostart import maybe_autostart_host
from mockworld.fakes._factories import TriageResultFactory
from repo_runtime import RepoRuntime

pytestmark = [pytest.mark.scenario, pytest.mark.timeout(60)]


async def _poll_until(condition, *, timeout_s: float = 15.0) -> None:
    """Poll *condition* with zero-sleep yields until True or *timeout_s* elapses."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(
        f"_poll_until: condition never became True within {timeout_s}s"
    )


async def _build_air_gapped_host_runtime(mock_world) -> tuple[RepoRuntime, Any]:
    """Build a host RepoRuntime whose orchestrator is air-gapped to MockWorld's
    Fakes — the exact wiring ``MockWorld._build_wired_orchestrator`` gives the
    dashboard's Start button, applied to a REAL ``RepoRuntime`` (no public seam
    exists for injecting ``services=`` into ``RepoRuntime.__init__``, so the
    freshly-constructed default orchestrator is swapped for the wired one —
    same private-attr technique the #10253 regression test's sibling scenarios
    use for MockWorld internals).
    """
    config = mock_world.harness.config
    bus = mock_world.harness.bus
    state = mock_world.harness.state

    orch = await mock_world._build_wired_orchestrator(config, bus, state)
    # _build_wired_orchestrator defaults pipeline_enabled=False for browser-
    # dashboard parity (the UI's own Play button gates it separately); the
    # REAL production host line (RepoRuntime.__init__, no pipeline_enabled
    # kwarg) defaults it True, so autostart's issues get processed for real.
    orch.pipeline_enabled = True

    host_runtime = RepoRuntime.from_shared(config, bus, state)
    host_runtime._orchestrator = orch
    return host_runtime, orch


@pytest.mark.asyncio
async def test_boot_autostart_starts_host_and_triages_seeded_issue(mock_world) -> None:
    mock_world.add_issue(1, "fix the thing", "body", labels=["hydraflow-find"])
    mock_world._llm.script_triage(
        1, [TriageResultFactory.create(issue_number=1, ready=True)]
    )

    host_runtime, _orch = await _build_air_gapped_host_runtime(mock_world)
    assert host_runtime.running is False

    started = await maybe_autostart_host(
        config=mock_world.harness.config,
        host_runtime=host_runtime,
        state=mock_world.harness.state,
        event_bus=mock_world.harness.bus,
    )

    try:
        assert started is True

        # host_runtime.start() only schedules orch.run() as a task — it needs
        # a chance to actually execute before `running` flips True.
        await _poll_until(lambda: host_runtime.running is True)

        # The real triage loop (running under the autostarted orchestrator)
        # consumes the scripted "ready" verdict and moves the issue off
        # hydraflow-find. Pipeline momentum may carry it further (e.g. into
        # planning, unscripted here) before this check runs, so assert
        # forward movement rather than pinning to the ready label exactly —
        # captured in one synchronous block (no await in between) so the
        # label snapshot can't shift mid-assertion.
        await _poll_until(
            lambda: "hydraflow-find" not in mock_world.github.issue(1).labels
        )
        labels = mock_world.github.issue(1).labels
        assert "hydraflow-find" not in labels
        assert any(label.startswith("hydraflow-") for label in labels), labels
    finally:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(host_runtime.stop(), timeout=15.0)


@pytest.mark.asyncio
async def test_boot_during_credit_pause_pauses_instead_of_erroring(
    mock_world, monkeypatch
) -> None:
    # Force the classic pause path rather than ADR-0119 GLM credit-failover
    # (default ON, requires ZAI_API_KEY): setting to "" (not deleting) makes
    # the key merely present-but-blank, so a stray dotenv reload mid-test
    # can't silently repopulate it and re-engage failover instead.
    monkeypatch.setenv("ZAI_API_KEY", "")
    monkeypatch.setenv("HYDRAFLOW_ZAI_API_KEY", "")

    mock_world.add_issue(2, "needs credits", "body", labels=["hydraflow-find"])
    mock_world._llm.script_triage(
        2, [TriageResultFactory.create(issue_number=2, ready=True)]
    )
    mock_world._llm.script_plan_credit_exhaustion(
        2,
        message="You've hit your weekly limit",
        resume_at=datetime.now(UTC) + timedelta(hours=1),
        authoritative=True,
    )

    host_runtime, orch = await _build_air_gapped_host_runtime(mock_world)

    started = await maybe_autostart_host(
        config=mock_world.harness.config,
        host_runtime=host_runtime,
        state=mock_world.harness.state,
        event_bus=mock_world.harness.bus,
    )

    try:
        assert started is True
        # Boots INTO the pause: the real orchestrator detects the scripted
        # CreditExhaustedError from its own plan() call and pauses itself —
        # nothing here mocks or forces the pause directly.
        await _poll_until(lambda: orch.credits_paused_until is not None)
        assert orch.credits_paused_until is not None
    finally:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(host_runtime.stop(), timeout=15.0)
