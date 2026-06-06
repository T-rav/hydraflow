"""Foundation scenario: a MockWorld-seeded 2-runtime registry aggregates.

Proves the widened MockWorld registry (Task 8) resolves through the real
RouteContext.resolve_runtimes resolver (Task 5) so Phases 2-5 inherit a
working multi-runtime scenario harness.
"""

from __future__ import annotations

import pytest

from config import Credentials
from dashboard_routes import RouteContext
from mockworld.seed import MockWorldSeed
from pr_manager import PRManager
from route_types import REPO_ALL

pytestmark = pytest.mark.scenario


def _ctx(config, event_bus, state, tmp_path, registry, default_slug):
    return RouteContext(
        config=config,
        credentials=Credentials(),
        event_bus=event_bus,
        state=state,
        pr_manager=PRManager(config, event_bus),
        get_orchestrator=lambda: None,
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=tmp_path / "no-dist",
        template_dir=tmp_path / "no-templates",
        registry=registry,
        default_repo_slug=default_slug,
    )


@pytest.mark.asyncio
async def test_seeded_registry_aggregates_through_resolver(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    seed = MockWorldSeed(
        repos=[
            ("owner/alpha", str(tmp_path / "alpha")),
            ("owner/beta", str(tmp_path / "beta")),
        ],
    )
    mock_world.apply_seed(seed)

    default_slug = config.repo.replace("/", "-")
    ctx = _ctx(config, event_bus, state, tmp_path, mock_world.registry, default_slug)

    # The host is not in the MockWorld registry (only seeded repos are), so the
    # aggregate is exactly the seeded runtimes — REPO_ALL == registry.all.
    all_slugs = [r[4] for r in ctx.resolve_runtimes(REPO_ALL)]
    assert all_slugs == ["owner-alpha", "owner-beta"]


@pytest.mark.asyncio
async def test_seeded_registry_scopes_to_one_repo(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    seed = MockWorldSeed(
        repos=[
            ("owner/alpha", str(tmp_path / "alpha")),
            ("owner/beta", str(tmp_path / "beta")),
        ],
    )
    mock_world.apply_seed(seed)

    default_slug = config.repo.replace("/", "-")
    ctx = _ctx(config, event_bus, state, tmp_path, mock_world.registry, default_slug)

    scoped = ctx.resolve_runtimes("owner-alpha")
    assert len(scoped) == 1
    assert scoped[0][4] == "owner-alpha"
