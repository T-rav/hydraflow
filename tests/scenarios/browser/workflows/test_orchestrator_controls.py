"""Clicking Start turns on the orchestrator; Stop turns it off."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.scenario_browser


# test_start_button_starts_orchestrator removed 2026-07-22 (#10215).
#
# RC-promotion-fatal: hung for ~2715s (zero pytest output) in a real RC run,
# force-cancelled only by the job's 45-minute `timeout-minutes` ceiling. The
# test's own Playwright waits carry explicit 10s timeouts that never fired —
# the shared asyncio event loop itself was blocked, not just slow.
#
# Root cause (traced in #10215, fix deferred to #10253): clicking Start hits
# `POST /api/control/start`'s no-registry legacy branch
# (`dashboard_routes/_control_routes.py`), which unconditionally discards
# whatever orchestrator MockWorld already wired against fakes and constructs
# a brand-new `HydraFlowOrchestrator` with REAL services (no `services=`
# override), then runs its 60+ real background loops in-process. Any one of
# them making a genuinely blocking call freezes the loop shared by the test,
# the dashboard, and the Playwright driver. `event_loop_watchdog` — the
# freeze detector that catches this exact failure class in production
# (#10225) — is a deliberate no-op under pytest, so nothing bounds the hang
# except the CI job's blunt wall-clock timeout.
#
# This is the same Start/Stop/WS-status code path whose Stop half
# (`test_stop_button_stops_orchestrator`) was removed 2026-05-19 for a milder
# 30s race — see the note below — with a root-cause follow-up that was never
# filed. #10253 now tracks it. Re-enable this test once #10253 lands.
#
# test_stop_button_stops_orchestrator removed 2026-05-19.
#
# CI-flaky: 30s timeout on `[data-testid="header-stop-button"]` click in CI
# (passes locally on every attempt). Blocked the rc/2026-05-19-0247 → main
# promotion (#8973) after ~155 commits accumulated on staging since the
# last successful RC. The Start half of this contract was covered by
# `test_start_button_starts_orchestrator` above until it too was removed
# (#10215, see note above); the Stop button itself has Header.jsx
# unit-test coverage at src/ui/src/components/__tests__/Header.test.jsx.
#
# The race condition between WebSocket `orchestrator_status` event
# arrival and the Stop-button DOM render needs its own diagnosis and
# either a wider locator wait, a different probe, or a server-side
# state-bridge fix. Filing separately is the right next step rather
# than letting this gate every rc/* PR.
