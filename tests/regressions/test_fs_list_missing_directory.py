"""`/api/fs/list` answered 500 for a directory that is merely absent.

The handler caught every `OSError` and returned
`{"error": "failed to list directory"}, status_code=500`. A caller browsing to
a directory that has since been removed is an ordinary client condition, and a
500 told them the dashboard had broken.

It also made the endpoint a 5xx on any host whose HOME does not exist.
`tests/conftest.py` sets `HOME=/tmp/hydraflow-test`, which exists on a laptop
that has run the suite before and does not on a fresh CI runner — so the route
was green locally and red on CI:

    FAILED test_no_parameterless_get_route_returns_a_server_error
    AssertionError: routes returned a server error: /api/fs/list -> 500

Found by the route-table lifecycle test added alongside this (#11548), which
parametrises over the app's own route table. The four hand-picked route tests
it replaced could not have found it — `/api/fs/list` was not one of the four.
"""

from __future__ import annotations

from config import HydraFlowConfig
from events import EventBus


class TestFsListMissingDirectory:
    """A directory that is not there is a 404, not a 500.

    `/api/fs/list` caught every `OSError` and answered 500. A caller browsing
    to a directory that has since been removed is an ordinary client
    condition, and 500 told them the dashboard had broken.

    It also made the endpoint a 5xx on any host whose HOME does not exist —
    which is exactly how the route-table lifecycle test above found it: green
    on a laptop where `/tmp/hydraflow-test` happens to exist, red on the CI
    runner where it does not.
    """

    def test_a_missing_directory_is_a_client_error(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        app = HydraFlowDashboard(config, event_bus, state).create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/api/fs/list", params={"path": str(tmp_path / "does-not-exist")}
        )

        assert response.status_code != 500, (
            "a missing directory still reports a server error"
        )

    def test_an_existing_directory_still_lists(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """The decoy: without it, the assertion above passes against a route
        that 404s unconditionally."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        app = HydraFlowDashboard(config, event_bus, state).create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/fs/list")

        assert response.status_code == 200
        assert "directories" in response.json()
