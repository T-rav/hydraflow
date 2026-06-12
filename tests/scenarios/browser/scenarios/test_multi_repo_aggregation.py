"""Tier-3 browser e2e: the multi-repo aggregate (repo=__all__) selection spine.

Proves the wired multi-repo UI a user sees against a real serving dashboard:
two registered repos surface in the RepoSelector, and picking "All repos"
reconnects the live WebSocket with ``?repo=__all__`` — the aggregate merged
stream from Phase 4-a. The backend aggregation + cross-repo dedup are proven at
the unit / integration tiers (``test_dashboard_ws_merged_multirepo.py`` and the
reducer vitest); this proves the selection + WS-param threading end to end in a
real browser.

Boot mirrors ``test_realtime_browser.py``: register repos Python-side via
``world.add_repo`` (so ``resolve_runtimes`` has >=2 runtimes and /api/repos
lists them), route /api/control/status to "running" so the board renders, then
drive the RepoSelector.
"""

from __future__ import annotations

import json

import pytest
from playwright.async_api import expect

pytestmark = pytest.mark.scenario_browser

# Tells React the orchestrator is "running" so panels render live content
# rather than the idle placeholder (mirrors test_realtime_browser.py).
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

# Capture the app's /ws socket(s) so the test can read each socket's URL and
# confirm the aggregate reconnect carries the repo=__all__ query. Runs before
# any page script. Filtered to /ws so a Vite HMR socket (if any) is ignored.
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


async def _route_control_status(page) -> None:
    async def _handle(route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle)


async def test_repo_selector_lists_repos_and_all_repos_uses_merged_ws(
    world, page
) -> None:
    """Two repos surface in the selector; "All repos" reconnects WS as __all__."""
    world.add_repo("owner/alpha", "/tmp/owner-alpha")
    world.add_repo("owner/beta", "/tmp/owner-beta")

    await page.add_init_script(_TRACK_WS_INIT_SCRIPT)
    url = await world.start_dashboard(with_orchestrator=False)
    await _route_control_status(page)
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    # The RepoSelector renders (multi-repo mode) and lists both registered repos.
    trigger = page.locator('[data-testid="repo-selector-trigger"]')
    await expect(trigger).to_be_visible(timeout=10_000)
    await trigger.click()

    dropdown = page.locator('[data-testid="repo-selector-dropdown"]')
    await expect(dropdown).to_be_visible()
    await expect(dropdown).to_contain_text("All repos")
    await expect(dropdown).to_contain_text("alpha")
    await expect(dropdown).to_contain_text("beta")

    # Pick "All repos" -> selectedRepoSlug = __all__ -> the WS reconnects with
    # the aggregate param (the merged fan-in stream).
    await dropdown.get_by_role("option", name="All repos").click()

    # A /ws socket connects with ?repo=__all__ (polled in-browser over the
    # captured sockets, so a pass is attributable to the real reconnect).
    await page.wait_for_function(
        "() => (window.__hfSockets || [])"
        ".some(w => String(w.url).includes('repo=__all__'))",
        timeout=10_000,
    )
