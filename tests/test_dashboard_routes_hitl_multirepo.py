"""HITL endpoints aggregate across repos and mutations target the row's repo.

Phase 3a of the multi-repo dashboard program: ``/api/hitl`` unions items across
repos for ``repo=__all__`` (tagging each with its repo slug and **including
stopped repos**), ``repo=<slug>`` scopes to one repo, and the mutations
(correct/skip/close/approve-process) resolve and act on the row's own
state/pr_manager/event_bus.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import HydraFlowConfig
from models import HITLItem
from route_types import REPO_ALL
from tests.conftest import make_state
from tests.helpers import (
    ConfigFactory,
    find_endpoint,
    make_dashboard_router,
    make_registry,
)


def _repo_cfg(tmp_path, name: str) -> HydraFlowConfig:
    (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return ConfigFactory.create(repo_root=tmp_path / name, repo=f"org/{name}")


def _patched_pr_managers(items_by_slug: dict[str, list[HITLItem]]):
    """Patch PRManager so each repo-scoped pr_manager_for returns a mock.

    pr_manager_for(cfg, bus) constructs PRManager(cfg, bus) for non-default
    configs; intercept it and hand back a per-repo AsyncMock keyed by slug.
    """
    managers: dict[str, AsyncMock] = {}

    def _factory(cfg, bus):
        slug = cfg.repo_slug
        mgr = managers.get(slug)
        if mgr is None:
            mgr = AsyncMock()
            mgr.list_hitl_items = AsyncMock(return_value=items_by_slug.get(slug, []))
            mgr.close_issue = AsyncMock()
            mgr.post_comment = AsyncMock()
            mgr.swap_pipeline_labels = AsyncMock()
            managers[slug] = mgr
        return mgr

    return patch("dashboard_routes._routes.PRManager", _factory), managers


@pytest.mark.asyncio
async def test_hitl_unions_and_tags_by_repo_including_stopped(
    config, event_bus, state, tmp_path
):
    cfg_a, cfg_b = _repo_cfg(tmp_path, "a"), _repo_cfg(tmp_path, "b")
    state_a, state_b = make_state(tmp_path / "sa"), make_state(tmp_path / "sb")
    state_a.set_hitl_cause(42, "CI failed in A")
    state_b.set_hitl_cause(42, "CI failed in B")

    orch_a = MagicMock(running=True)
    orch_a.get_hitl_status.return_value = "pending"
    registry = make_registry(
        {
            "slug": "org-a",
            "config": cfg_a,
            "state": state_a,
            "event_bus": event_bus,
            "orchestrator": orch_a,
            "running": True,
        },
        # org-b is STOPPED (no orchestrator, running=False) — must still appear.
        {
            "slug": "org-b",
            "config": cfg_b,
            "state": state_b,
            "event_bus": event_bus,
            "orchestrator": None,
            "running": False,
        },
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    get_hitl = find_endpoint(router, "/api/hitl")

    items_by_slug = {
        "org-a": [HITLItem(issue=42, title="A bug", pr=101)],
        "org-b": [HITLItem(issue=42, title="B bug", pr=202)],
    }
    pman, _ = _patched_pr_managers(items_by_slug)
    with pman:
        resp = await get_hitl(repo=REPO_ALL)
    rows = json.loads(resp.body)

    # Both repos present (incl. STOPPED org-b), each tagged with its slug.
    assert {r["repo"] for r in rows} == {"org-a", "org-b"}
    # Colliding issue #42 from two repos → two distinct rows, each enriched
    # from its OWN repo's state (the latent-bug fix).
    by_repo = {r["repo"]: r for r in rows}
    assert by_repo["org-a"]["cause"] == "CI failed in A"
    assert by_repo["org-b"]["cause"] == "CI failed in B"


@pytest.mark.asyncio
async def test_hitl_scopes_to_one_repo(config, event_bus, state, tmp_path):
    cfg_a, cfg_b = _repo_cfg(tmp_path, "a"), _repo_cfg(tmp_path, "b")
    state_a, state_b = make_state(tmp_path / "sa"), make_state(tmp_path / "sb")
    state_a.set_hitl_cause(1, "A")
    state_b.set_hitl_cause(2, "B")
    registry = make_registry(
        {
            "slug": "org-a",
            "config": cfg_a,
            "state": state_a,
            "event_bus": event_bus,
            "orchestrator": None,
            "running": True,
        },
        {
            "slug": "org-b",
            "config": cfg_b,
            "state": state_b,
            "event_bus": event_bus,
            "orchestrator": None,
            "running": True,
        },
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    get_hitl = find_endpoint(router, "/api/hitl")

    pman, _ = _patched_pr_managers(
        {
            "org-a": [HITLItem(issue=1, title="A", pr=1)],
            "org-b": [HITLItem(issue=2, title="B", pr=2)],
        }
    )
    with pman:
        resp = await get_hitl(repo="org-b")
    rows = json.loads(resp.body)
    assert {r["repo"] for r in rows} == {"org-b"}
    assert {r["issue"] for r in rows} == {2}


@pytest.mark.asyncio
async def test_hitl_default_repo_unchanged_without_registry(
    config, event_bus, state, tmp_path
):
    router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
    state.set_hitl_cause(7, "default cause")
    pr_mgr.list_hitl_items = AsyncMock(return_value=[HITLItem(issue=7, title="x")])
    get_hitl = find_endpoint(router, "/api/hitl")

    resp = await get_hitl()
    rows = json.loads(resp.body)
    assert len(rows) == 1
    assert rows[0]["cause"] == "default cause"


@pytest.mark.asyncio
async def test_hitl_close_targets_row_repo(config, event_bus, state, tmp_path):
    cfg_a, cfg_b = _repo_cfg(tmp_path, "a"), _repo_cfg(tmp_path, "b")
    state_a, state_b = make_state(tmp_path / "sa"), make_state(tmp_path / "sb")
    orch_b = MagicMock(running=True)
    registry = make_registry(
        {
            "slug": "org-a",
            "config": cfg_a,
            "state": state_a,
            "event_bus": event_bus,
            "orchestrator": MagicMock(running=True),
            "running": True,
        },
        {
            "slug": "org-b",
            "config": cfg_b,
            "state": state_b,
            "event_bus": event_bus,
            "orchestrator": orch_b,
            "running": True,
        },
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    hitl_close = find_endpoint(router, "/api/hitl/{issue_number}/close", "POST")

    pman, managers = _patched_pr_managers({})
    from models import HITLCloseRequest

    with pman:
        resp = await hitl_close(42, HITLCloseRequest(reason="done"), repo="org-b")
    assert json.loads(resp.body)["status"] == "ok"

    # B's pr_manager closed the issue; A's was never constructed/touched.
    assert "org-b" in managers
    managers["org-b"].close_issue.assert_awaited_once_with(42)
    assert "org-a" not in managers
    # B's orchestrator cleared HITL state; A's did not.
    orch_b.skip_hitl_issue.assert_called_once_with(42)


@pytest.mark.asyncio
async def test_hitl_mutation_rejects_all_repos(config, event_bus, state, tmp_path):
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    hitl_close = find_endpoint(router, "/api/hitl/{issue_number}/close", "POST")
    from models import HITLCloseRequest

    resp = await hitl_close(42, HITLCloseRequest(reason="x"), repo=REPO_ALL)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_hitl_summary_rejects_all_repos(config, event_bus, state, tmp_path):
    # A single issue's summary is repo-scoped — repo=__all__ has no meaning.
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    summary = find_endpoint(router, "/api/hitl/{issue_number}/summary")
    resp = await summary(42, repo=REPO_ALL)
    assert resp.status_code == 400
