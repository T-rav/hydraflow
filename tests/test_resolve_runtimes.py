"""RouteContext.resolve_runtimes — the plural per-repo / aggregate resolver."""

from __future__ import annotations

from config import Credentials
from dashboard_routes import RouteContext
from events import EventBus
from route_types import REPO_ALL
from state import StateTracker
from tests.helpers import ConfigFactory, make_registry


def _make_ctx(
    config, event_bus, state, tmp_path, *, registry=None, default_repo_slug=None
):
    from pr_manager import PRManager

    pr_mgr = PRManager(config, event_bus)
    return RouteContext(
        config=config,
        credentials=Credentials(),
        event_bus=event_bus,
        state=state,
        pr_manager=pr_mgr,
        get_orchestrator=lambda: None,
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=tmp_path / "no-dist",
        template_dir=tmp_path / "no-templates",
        registry=registry,
        default_repo_slug=default_repo_slug,
    )


def test_no_registry_all_returns_single_default(config, event_bus, state, tmp_path):
    ctx = _make_ctx(
        config, event_bus, state, tmp_path, default_repo_slug="test-org-test-repo"
    )

    result = ctx.resolve_runtimes(REPO_ALL)

    assert len(result) == 1
    cfg, st, bus, get_orch, slug = result[0]
    assert cfg is config
    assert st is state
    assert bus is event_bus
    assert slug == "test-org-test-repo"
    assert callable(get_orch)


def test_none_returns_single_default(config, event_bus, state, tmp_path):
    ctx = _make_ctx(
        config, event_bus, state, tmp_path, default_repo_slug="test-org-test-repo"
    )

    result = ctx.resolve_runtimes(None)

    assert len(result) == 1
    assert result[0][4] == "test-org-test-repo"


def test_concrete_slug_returns_single_tagged(config, event_bus, state, tmp_path):
    alpha_cfg = ConfigFactory.create(repo="owner/alpha", repo_root=tmp_path / "alpha")
    alpha_state = StateTracker(tmp_path / "alpha-state.json")
    alpha_bus = EventBus()
    registry = make_registry(
        {
            "slug": "owner/alpha",
            "config": alpha_cfg,
            "state": alpha_state,
            "event_bus": alpha_bus,
        }
    )
    ctx = _make_ctx(config, event_bus, state, tmp_path, registry=registry)

    result = ctx.resolve_runtimes("owner-alpha")

    assert len(result) == 1
    cfg, st, bus, _get_orch, slug = result[0]
    assert cfg is alpha_cfg
    assert st is alpha_state
    assert bus is alpha_bus
    assert slug == "owner-alpha"


def test_repo_all_returns_default_plus_all(config, event_bus, state, tmp_path):
    registry = make_registry({"slug": "owner-alpha"}, {"slug": "owner-beta"})
    ctx = _make_ctx(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="test-org-test-repo",
    )

    result = ctx.resolve_runtimes(REPO_ALL)

    slugs = [r[4] for r in result]
    assert slugs == ["test-org-test-repo", "owner-alpha", "owner-beta"]


def test_repo_all_case_insensitive(config, event_bus, state, tmp_path):
    registry = make_registry({"slug": "owner-alpha"})
    ctx = _make_ctx(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="test-org-test-repo",
    )

    assert len(ctx.resolve_runtimes("__ALL__")) == 2


def test_repo_all_dedups_default_in_registry(config, event_bus, state, tmp_path):
    # config.repo defaults to "test-org/test-repo"; a registry entry for the
    # same repo must not double-list.
    registry = make_registry({"slug": "test-org-test-repo"}, {"slug": "owner-alpha"})
    ctx = _make_ctx(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="test-org-test-repo",
    )

    slugs = [r[4] for r in ctx.resolve_runtimes(REPO_ALL)]

    assert slugs.count("test-org-test-repo") == 1
    assert "owner-alpha" in slugs


def test_unknown_slug_tags_default_not_bogus(config, event_bus, state, tmp_path):
    registry = make_registry({"slug": "owner-alpha"})
    ctx = _make_ctx(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="test-org-test-repo",
    )

    result = ctx.resolve_runtimes("ghost-repo")

    assert len(result) == 1
    assert result[0][4] == "test-org-test-repo"  # the truth, never "ghost-repo"


def test_singular_resolve_runtime_unchanged(config, event_bus, state, tmp_path):
    # Regression-lock: the singular still returns a 4-tuple.
    ctx = _make_ctx(config, event_bus, state, tmp_path)

    result = ctx.resolve_runtime(None)

    assert len(result) == 4
