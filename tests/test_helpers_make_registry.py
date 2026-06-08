"""make_registry builds a real RepoRuntimeRegistry of duck-typed runtimes."""

from __future__ import annotations

from tests.helpers import make_registry


def test_builds_dash_keyed_runtimes() -> None:
    registry = make_registry({"slug": "owner/alpha"}, {"slug": "owner-beta"})

    assert set(registry.slugs) == {"owner-alpha", "owner-beta"}
    assert registry.get("owner/alpha").slug == "owner-alpha"
    assert len(registry) == 2


def test_runtime_defaults() -> None:
    registry = make_registry({"slug": "owner-alpha"})
    runtime = registry.get("owner-alpha")

    assert runtime.orchestrator is None
    assert runtime.running is False
    assert runtime.last_error is None


def test_runtime_carries_passed_fields() -> None:
    sentinel_cfg = object()
    registry = make_registry(
        {"slug": "owner-alpha", "config": sentinel_cfg, "running": True}
    )
    runtime = registry.get("owner-alpha")

    assert runtime.config is sentinel_cfg
    assert runtime.running is True
