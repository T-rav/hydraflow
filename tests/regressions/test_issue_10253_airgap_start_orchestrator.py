"""Regression: the browser-scenario Start button must not wedge the shared loop.

#10253 / #10215. ``MockWorld._build_wired_orchestrator`` — the orchestrator the
dashboard Start button runs — used to build a REAL ``ServiceRegistry`` (real
Docker ``SubprocessRunner``, real ``gh``) and monkeypatch only the four PIPELINE
runners; every one of the ~60 BACKGROUND caretaker loops kept its real adapter.
Clicking Start ran those loops in-process and a single blocking caretaker call
froze the event loop shared by the test, the dashboard, and the Playwright
driver — a 2715s hang, force-cancelled only by the CI job's 45-minute ceiling
(``test_start_button_starts_orchestrator``, removed by #10215).

This pins the two halves of the fix:

1. the wired orch's background-loop-facing services are air-gapped Fakes
   (a DETERMINISTIC guard — the old real-orch wiring fails it), and
2. a REAL ``run()`` keeps the shared event loop responsive — a bounded
   ``asyncio.wait_for`` turns any residual wedge into a seconds-fast failure
   instead of the 45-minute CI hang.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

# Backstop only: the load-bearing bound is the inner ``asyncio.wait_for`` below.
# A truly synchronous block can't be interrupted by wait_for, so cap the whole
# test too — a wedge must fail in seconds, never consume the CI budget.
pytestmark = pytest.mark.timeout(60)


async def test_wired_start_orchestrator_is_airgapped_and_stays_responsive(
    tmp_path,
) -> None:
    from mockworld.fakes.fake_issue_fetcher import FakeIssueFetcher
    from mockworld.fakes.fake_issue_store import FakeIssueStore
    from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    world.add_issue(1, "t", "b", labels=["hydraflow-find"])
    orch = await world._build_wired_orchestrator(
        world.harness.config, world.harness.bus, world.harness.state
    )

    # (1) Air-gap wiring — a deterministic guard that fails BEFORE the hazardous
    #     run() below on the pre-#10253 real-orch wiring (real Docker runner /
    #     gh / IssueStore). Every background loop reaches these adapters, so all
    #     of them must be Fakes for the fleet to be non-blocking.
    assert isinstance(orch._svc.subprocess_runner, FakeSubprocessRunner)
    assert isinstance(orch._svc.store, FakeIssueStore)
    assert isinstance(orch._svc.fetcher, FakeIssueFetcher)
    assert orch._svc.prs is world.github

    # (2) Responsiveness under a REAL run() — clicking Start schedules
    #     ``orch.run()``, which supervises the ~60 background loops. A single
    #     blocking caretaker would freeze the loop; a concurrent heartbeat that
    #     completes proves the shared loop stayed responsive after Start.
    run_task = asyncio.create_task(orch.run())
    try:

        async def _heartbeat() -> str:
            # ~1s of concurrent activity while the loop fleet spins up; each
            # await must return promptly or the loop is wedged.
            for _ in range(20):
                await asyncio.sleep(0.05)
            return "responsive"

        assert await asyncio.wait_for(_heartbeat(), timeout=5.0) == "responsive"
    finally:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(orch.stop(), timeout=15.0)
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(run_task, return_exceptions=True), timeout=15.0
            )
