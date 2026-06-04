"""MockWorld scenario for HoneycombIngestLoop (low-noise SLO ingestion).

Drives the loop end-to-end against ``FakeGitHub`` (the canonical PRPort
fake) through ``MockWorld.run_with_loops`` to assert the load-bearing
low-noise behaviour:

* No issue is filed on the first observation of a breach.
* An issue IS filed once the breach persists for the sustained-poll gate.
* The filed issue lands in FakeGitHub with the dedup marker.
* The issue is auto-closed once the SLO recovers.

The loop ships DEFAULT-DISABLED, so the scenario flips it on via
``config_overrides`` and injects a fake httpx client + mgmt key through the
seeded ports (mirrors ``catalog/loop_registrations._build_honeycomb_ingest``).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeHoneycombClient:
    """Async-context-manager fake; routes URL substring → canned payload."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes

    async def __aenter__(self) -> _FakeHoneycombClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict | None = None) -> _FakeResponse:
        for prefix, payload in self.routes.items():
            if prefix in url:
                return _FakeResponse(payload)
        return _FakeResponse([])


def _slo(budget_remaining: float) -> dict:
    return {
        "id": "slo-checkout",
        "name": "checkout availability",
        "budget_remaining": budget_remaining,
        "target_per_million": 999_000,
    }


_OVERRIDES = {
    "honeycomb_ingest_loop_enabled": True,
    "honeycomb_datasets": "prod",
    "honeycomb_min_sustained_polls": 2,
    "honeycomb_slo_budget_threshold_pct": 0.0,
}


class TestHoneycombIngestScenario:
    async def test_sustained_breach_files_then_recovers(self, tmp_path) -> None:
        from config import Credentials

        world = MockWorld(tmp_path)
        routes: dict[str, Any] = {
            "/1/slos/": [_slo(0.0)],  # budget exhausted -> breaching
            "/1/burn_alerts/": [],
        }
        _seed_ports(
            world,
            honeycomb_credentials=Credentials(honeycomb_mgmt_api_key="hcaik_test"),
            honeycomb_http_factory=lambda: _FakeHoneycombClient(routes),
            honeycomb_state_path=tmp_path / "hc_state.json",
        )

        # Poll 1: first observation — the sustained gate must suppress filing.
        r1 = await world.run_with_loops(
            ["honeycomb_ingest"], cycles=1, config_overrides=_OVERRIDES
        )
        assert r1["honeycomb_ingest"]["issues_created"] == 0
        assert not world._github._issues

        # Poll 2: breach sustained -> file exactly one issue with the marker.
        r2 = await world.run_with_loops(
            ["honeycomb_ingest"], cycles=1, config_overrides=_OVERRIDES
        )
        assert r2["honeycomb_ingest"]["issues_created"] == 1
        filed = list(world._github._issues.values())
        assert len(filed) == 1
        assert "<!-- [honeycomb:slo-checkout] -->" in filed[0].body
        issue_number = filed[0].number
        assert filed[0].state == "open"

        # Poll 3: SLO recovers -> our issue is auto-closed.
        routes["/1/slos/"] = [_slo(0.6)]
        r3 = await world.run_with_loops(
            ["honeycomb_ingest"], cycles=1, config_overrides=_OVERRIDES
        )
        assert r3["honeycomb_ingest"]["issues_closed"] == 1
        assert world._github._issues[issue_number].state == "closed"
        recovered_comments = [
            body
            for (target, body) in world._github._comments
            if target == issue_number and "recovered" in body
        ]
        assert recovered_comments, "expected a 'recovered' auto-close comment"

    async def test_disabled_by_default_is_noop(self, tmp_path) -> None:
        from config import Credentials

        world = MockWorld(tmp_path)
        routes = {"/1/slos/": [_slo(0.0)], "/1/burn_alerts/": []}
        _seed_ports(
            world,
            honeycomb_credentials=Credentials(honeycomb_mgmt_api_key="hcaik_test"),
            honeycomb_http_factory=lambda: _FakeHoneycombClient(routes),
            honeycomb_state_path=tmp_path / "hc_state.json",
        )
        # No config_overrides -> loop ships default-disabled -> no-op.
        result = await world.run_with_loops(["honeycomb_ingest"], cycles=3)
        assert result["honeycomb_ingest"] == {"status": "disabled"}
        assert not world._github._issues
