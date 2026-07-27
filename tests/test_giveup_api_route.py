"""GET /api/give-up surfaces the give-up window state (#10735).

Proves deliverable 3: per-issue cycle count + threshold + which self-solve
action fired are visible on the API.
"""

from __future__ import annotations

import json

import pytest

from tests.helpers import find_endpoint, make_dashboard_router


class TestGiveUpRoute:
    def test_route_is_registered(self, config, event_bus, state, tmp_path) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes}
        assert "/api/give-up" in paths

    @pytest.mark.asyncio
    async def test_returns_thresholds_and_per_issue_state(
        self, config, event_bus, state, tmp_path
    ) -> None:
        # Seed a give-up window that fired a decompose self-solve.
        state.record_give_up_event(10731, "plan_retry", 1000.0)
        state.record_give_up_event(10731, "plan_retry", 1001.0)
        state.record_give_up_action(10731, "plan_retry", "decompose", 1002.0)

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, registry=None
        )
        ep = find_endpoint(router, "/api/give-up")
        resp = await ep()
        assert resp.status_code == 200
        payload = json.loads(resp.body)

        # Thresholds for every child-class are echoed.
        assert set(payload["thresholds"]) == {"build", "review", "loop", "plan_retry"}
        assert payload["thresholds"]["plan_retry"]["max_restarts"] == 2

        # Per-issue give-up state: cycle count + fired self-solve action.
        issue = payload["issues"]["10731"]["plan_retry"]
        assert issue["cycle_count"] == 2
        assert issue["last_action"] == "decompose"

    @pytest.mark.asyncio
    async def test_empty_when_nothing_tracked(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, registry=None
        )
        ep = find_endpoint(router, "/api/give-up")
        resp = await ep()
        payload = json.loads(resp.body)
        assert payload["issues"] == {}
        assert "enabled" in payload
