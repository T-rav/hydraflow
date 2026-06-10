"""Tier-3 browser e2e: pipeline CARDS aggregate across repos under repo=__all__.

The lighter `test_multi_repo_aggregation.py` proves the RepoSelector + WS-param
wiring; this proves the actual board content. Two repos are registered with a
pipeline-surfacing orchestrator (`add_repo(..., with_pipeline=True)`) and each
seeded with its own active issue. Picking "All repos" must render BOTH repos'
flow-dots; picking a single repo must scope the board to that repo only.

Backend aggregation is proven at unit/scenario tiers
(`test_dashboard_routes_workstream_multirepo.py`,
`test_multi_repo_aggregate_endpoints.py`); this is the served-board view a user
sees in a real browser.
"""

from __future__ import annotations

import json

import pytest
from playwright.async_api import expect

from issue_store import STAGE_READY

pytestmark = pytest.mark.scenario_browser

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


async def _route_control_status(page) -> None:
    async def _handle(route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle)


async def test_all_repos_renders_both_repos_pipeline_cards(world, page) -> None:
    """ "All repos" aggregates both repos' cards; a single repo scopes the board."""
    world.add_repo("owner/alpha", "/tmp/owner-alpha", with_pipeline=True)
    world.add_repo("owner/beta", "/tmp/owner-beta", with_pipeline=True)
    # Distinct issue numbers per repo so each flow-dot is unambiguous.
    world.registry.get("owner-alpha").orchestrator.issue_store.mark_active(
        1, STAGE_READY
    )
    world.registry.get("owner-beta").orchestrator.issue_store.mark_active(
        101, STAGE_READY
    )

    url = await world.start_dashboard(with_orchestrator=False)
    await _route_control_status(page)
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    # Select "All repos" — the board re-fetches /api/pipeline?repo=__all__.
    await page.locator('[data-testid="repo-selector-trigger"]').click()
    dropdown = page.locator('[data-testid="repo-selector-dropdown"]')
    await expect(dropdown).to_be_visible()
    await dropdown.get_by_role("option", name="All repos").click()

    # Both repos' cards render under the aggregate view.
    await expect(page.locator('[data-testid="flow-dot-1"]')).to_be_visible(
        timeout=10_000
    )
    await expect(page.locator('[data-testid="flow-dot-101"]')).to_be_visible(
        timeout=10_000
    )

    # Scope to owner-alpha — only its card remains.
    await page.locator('[data-testid="repo-selector-trigger"]').click()
    await dropdown.get_by_role("option", name="owner-alpha").click()
    await expect(page.locator('[data-testid="flow-dot-101"]')).to_have_count(
        0, timeout=10_000
    )
    await expect(page.locator('[data-testid="flow-dot-1"]')).to_be_visible()
