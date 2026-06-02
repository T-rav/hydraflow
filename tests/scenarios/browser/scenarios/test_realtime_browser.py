"""Tier-3 browser e2e for the WS-RT real-time work-visualization spine.

These tests are the sandbox-e2e layer of the WS-RT pyramid (PR3 snapshot
push, PR4 optimistic-layer removal, PR5 reconnect resilience + ephemeral
snapshots). The unit (``test_events.py``, ``HydraFlowContext.test.jsx``) and
MockWorld-scenario (``test_pipeline_snapshot_scenario.py``) layers prove the
mechanics in isolation; these prove the wired behaviour a user sees in a
real browser against a real serving dashboard:

  1. A card moves stage -> merged WITHOUT a page reload, delivered over the
     live WebSocket ``PIPELINE_SNAPSHOT`` push — asserted within a window far
     shorter than the 30s REST safety-net poll, so a pass is attributable to
     the WS push and NOT the poll. The card never vanishes during handoff.

  2. After the WebSocket drops, the board re-syncs to authoritative server
     state on reconnect (``onopen`` re-fetches ``/api/pipeline``) — the card
     mutated while disconnected appears, is not lost, and is not duplicated.
     With PIPELINE_SNAPSHOT now ephemeral (PR5) there is no stale historical
     frame to replay, so the reconnect cannot clobber fresh board state.

Boot pattern mirrors ``test_happy_browser.py``: seed + drive state Python-side
through the harness IssueStore, boot the dashboard with the lightweight shim
(``with_orchestrator=False``), then assert the rendered board. The difference
here is that state mutations happen AFTER the page is connected, so the board
must update live rather than only hydrating the final state on mount.
"""

from __future__ import annotations

import json

import pytest
from playwright.async_api import expect

from issue_store import STAGE_READY
from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario_browser

# Tells React the orchestrator is "running" so panels render live content
# rather than the idle placeholder (mirrors test_happy_browser.py).
_RUNNING_CONTROL_STATUS = {
    "status": "running",
    "credits_paused_until": None,
    "current_session_id": None,
    "config": {
        "app_version": "0.0.0",
        "latest_version": "",
        "update_available": False,
        "repo": "T-rav/hydraflow",
        "ready_label": ["hydraflow-ready"],
        "find_label": ["hydraflow-find"],
        "planner_label": ["hydraflow-plan"],
        "review_label": ["hydraflow-review"],
        "hitl_label": ["hydraflow-hitl"],
        "hitl_active_label": ["hydraflow-hitl-active"],
        "fixed_label": ["hydraflow-fixed"],
        "max_triagers": 1,
        "max_workers": 2,
        "max_planners": 1,
        "max_reviewers": 1,
        "max_hitl_workers": 1,
        "batch_size": 5,
        "model": "claude-opus-4-5",
        "pr_unstick_batch_size": 3,
        "workspace_base": "/tmp/hydraflow-worktrees",
    },
}

# Capture the app's /ws socket(s) so a test can force a clean close to exercise
# reconnect deterministically (no network emulation, which is flaky against
# localhost). Runs before any page script, so the app's WebSocket is a
# TrackedWS instance. Filtered to /ws so a Vite HMR socket (if any) is ignored.
_TRACK_WS_INIT_SCRIPT = """
window.__hfSockets = [];
class TrackedWS extends WebSocket {
  constructor(...args) {
    super(...args);
    if (String(args[0]).includes('/ws')) window.__hfSockets.push(this);
  }
}
window.WebSocket = TrackedWS;
"""

# Assert the live merged move within this window. It is comfortably below the
# 30s REST safety-net poll (PIPELINE_POLL_SAFETY_NET_MS), so a pass proves the
# update arrived via the live WS PIPELINE_SNAPSHOT push, not the fallback poll.
_LIVE_PUSH_TIMEOUT_MS = 8_000


async def _route_control_status(page) -> None:
    async def _handle(route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle)


async def test_card_progresses_to_merged_live_via_ws_push(world, page) -> None:
    """A card advances to the merged stage live over the WS, no reload.

    Seeds an issue active in the implement stage, connects the dashboard, then
    — while connected — completes and merges it Python-side. The merge must
    surface on the board within _LIVE_PUSH_TIMEOUT_MS (< the 30s poll), which
    is only possible via the live PIPELINE_SNAPSHOT push. The issue's flow-dot
    stays visible throughout, proving the card does not vanish on handoff.
    """
    # --- Seed: issue #1 active in the implement stage (backend "ready"). ---
    IssueBuilder().numbered(1).titled("Wire the live board").bodied(
        "Make the pipeline board update in real time"
    ).at(world)
    store = world._harness.store
    store.mark_active(1, STAGE_READY)  # ready -> frontend "implement"

    # --- Boot + connect. ---
    url = await world.start_dashboard(with_orchestrator=False)
    await _route_control_status(page)
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    # --- Initial board: card present, NOT yet merged. ---
    flow_dot = page.locator('[data-testid="flow-dot-1"]')
    await expect(flow_dot).to_be_visible(timeout=10_000)
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).to_contain_text("0 merged", timeout=10_000)

    # --- Mutate while connected: complete + merge -> live WS snapshot push. ---
    store.mark_complete(1)  # leaves the implement stage
    store.mark_merged(1)  # enters the merged stage

    # --- The move must appear live, faster than the 30s safety-net poll. ---
    await expect(merged_header).to_contain_text(
        "1 merged", timeout=_LIVE_PUSH_TIMEOUT_MS
    )
    # The card did not vanish during the stage handoff.
    await expect(flow_dot).to_be_visible()


async def test_board_resyncs_after_ws_reconnect(world, page) -> None:
    """The board re-syncs to authoritative state after a WS drop + reconnect.

    Connects with a card in implement, force-closes the WS, mutates the card to
    merged while disconnected, then lets the app reconnect. On reconnect onopen
    re-fetches /api/pipeline, so the board must reflect the merge — the card is
    neither lost nor duplicated. PIPELINE_SNAPSHOT is ephemeral (PR5), so no
    stale historical frame is replayed to clobber the fresh state.
    """
    IssueBuilder().numbered(1).titled("Survive a reconnect").bodied(
        "Board must re-sync after the socket drops"
    ).at(world)
    store = world._harness.store
    store.mark_active(1, STAGE_READY)

    # Install the WS tracker BEFORE navigation so the app's socket is captured.
    await page.add_init_script(_TRACK_WS_INIT_SCRIPT)

    url = await world.start_dashboard(with_orchestrator=False)
    await _route_control_status(page)
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    flow_dot = page.locator('[data-testid="flow-dot-1"]')
    await expect(flow_dot).to_be_visible(timeout=10_000)
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).to_contain_text("0 merged", timeout=10_000)

    # --- Force a clean WS close; the app should report disconnected. ---
    closed = await page.evaluate(
        "() => { const s = (window.__hfSockets || []);"
        " s.forEach(w => w.close()); return s.length; }"
    )
    assert closed >= 1, "no /ws socket was captured to close"
    await page.wait_for_selector('body[data-connected="false"]', timeout=10_000)

    # --- Mutate while disconnected: the live push has no subscriber and is
    #     dropped; only the reconnect re-fetch can surface this state. ---
    store.mark_complete(1)
    store.mark_merged(1)

    # --- Reconnect (exponential backoff) -> onopen re-fetches /api/pipeline. ---
    await page.wait_for_selector('body[data-connected="true"]', timeout=15_000)

    # --- Board re-synced authoritatively: merged exactly once, card intact. ---
    await expect(merged_header).to_contain_text("1 merged", timeout=10_000)
    await expect(flow_dot).to_be_visible()
    assert await flow_dot.count() == 1, "card was duplicated across the reconnect"
