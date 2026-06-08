"""Regression: MockWorld must not hand the dashboard an EMPTY repo registry.

Issue #9359 — #9347 (multi-repo dashboard Phase 1) made MockWorld always pass
its ``RepoRuntimeRegistry`` to the dashboard, even when no repo was registered.
A non-None-but-empty registry flips the dashboard onto its multi-repo branches
for single-repo browser scenarios: POST /api/control/start runs
``registry.start_all()`` over zero runtimes (orchestrator stuck "idle") and
resolve_runtime / is_repo_pipeline_active resolve an empty set (cards "0 merged",
real-gh 401). The fix: pass the registry only once a repo is actually
registered; otherwise fall back to the host/legacy path (pre-#9347 behaviour).

This is a fast guard so the invariant is checked without the (slow, separate)
browser-scenario gate that only runs at rc/* -> main promotion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld


@pytest.mark.asyncio
async def test_dashboard_gets_no_registry_when_no_repos_registered(
    tmp_path: Path,
) -> None:
    """With no add_repo, the dashboard must receive registry=None (host path)."""
    world = MockWorld(tmp_path)
    try:
        await world.start_dashboard(with_orchestrator=False)
        assert world._dashboard is not None
        # The empty registry must NOT be handed to the dashboard — otherwise the
        # registry-gated control/data routes resolve an empty set.
        assert world._dashboard._registry is None
    finally:
        await world.stop_dashboard()


@pytest.mark.asyncio
async def test_dashboard_gets_registry_once_a_repo_is_registered(
    tmp_path: Path,
) -> None:
    """When a repo IS registered, the dashboard receives the live registry."""
    world = MockWorld(tmp_path)
    try:
        world.add_repo("acme/widgets", str(tmp_path / "widgets"))
        await world.start_dashboard(with_orchestrator=False)
        assert world._dashboard is not None
        assert world._dashboard._registry is world._registry
        assert len(world._dashboard._registry) >= 1
    finally:
        await world.stop_dashboard()
