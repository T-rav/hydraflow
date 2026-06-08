"""Integration smoke test for the unified host-repo-as-runtime wiring.

Mirrors server.py's boot wiring — the host repo registered as a
:class:`RepoRuntime` sharing the app-level bus/state — and verifies the
dashboard resolves it through the registry. This is the invariant that lets
the ``_is_default_repo`` special-casing be deleted: the host is just another
registered factory line.
"""

from __future__ import annotations

from dashboard import HydraFlowDashboard
from repo_runtime import RepoRuntime, RepoRuntimeRegistry


def _boot_like_server(config, event_bus, state):
    """Replicate server.py's host-runtime registration."""
    registry = RepoRuntimeRegistry()
    host = RepoRuntime.from_shared(config, event_bus, state)
    registry.add(host)
    return registry, host


class TestHostRuntimeWiring:
    def test_host_registered_under_default_slug_sharing_bus_and_state(
        self, config, event_bus, state
    ) -> None:
        registry, host = _boot_like_server(config, event_bus, state)
        assert registry.get(config.repo) is host
        assert host.event_bus is event_bus
        assert host.state is state

    def test_dashboard_get_orchestrator_returns_host_orchestrator(
        self, config, event_bus, state
    ) -> None:
        registry, host = _boot_like_server(config, event_bus, state)
        dashboard = HydraFlowDashboard(
            config, event_bus, state, host_runtime=host, registry=registry
        )
        assert dashboard._get_orchestrator() is host.orchestrator

    def test_runtimes_endpoint_lists_host(self, config, event_bus, state) -> None:
        from fastapi.testclient import TestClient

        registry, host = _boot_like_server(config, event_bus, state)
        dashboard = HydraFlowDashboard(
            config, event_bus, state, host_runtime=host, registry=registry
        )
        client = TestClient(dashboard.create_app())

        resp = client.get("/api/runtimes")

        assert resp.status_code == 200
        slugs = [r["slug"] for r in resp.json()["runtimes"]]
        assert host.slug in slugs

    def test_control_status_without_repo_resolves_host(
        self, config, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        registry, host = _boot_like_server(config, event_bus, state)
        dashboard = HydraFlowDashboard(
            config, event_bus, state, host_runtime=host, registry=registry
        )
        client = TestClient(dashboard.create_app())

        # No repo param -> resolve_runtime(None) must resolve to the host
        # (shared bus/state) without error.
        resp = client.get("/api/control/status")

        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)
