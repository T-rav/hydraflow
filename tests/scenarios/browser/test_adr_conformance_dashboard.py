"""Browser/sandbox-tier: the ADR conformance dashboard route serves via the booted dashboard.

Mirrors ``test_smoke.py``: boots the dashboard through the ``world`` fixture and
asserts the conformance read-route (``/api/adr-conformance``, added for ADR-0100)
is wired and serves. This is the Tier-C companion to the in-process producer e2e
(``tests/scenarios/test_adr_conformance_e2e.py``) — it proves the route is
reachable through the real served dashboard, not just callable in-process.

Empty ``{}`` is the correct response when no conformance run has persisted a
jsonl yet (a freshly booted dashboard); the assertion is on reachability +
JSON-object shape, matching the smoke test's rigor. Verified equivalently
against the dockerized sandbox (`make sandbox-up` → GET :5555/api/adr-conformance
→ 200 {}).
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.scenario_browser
async def test_adr_conformance_route_serves(world):
    url = await world.start_dashboard()

    async with httpx.AsyncClient() as client:
        response = await client.get(url + "/api/adr-conformance")

    assert response.status_code == 200
    body = response.json()
    # dict of {adr_id: latest-conformance-row}; empty until a loop tick persists.
    assert isinstance(body, dict)


@pytest.mark.scenario_browser
async def test_adr_conformance_route_serves_with_orchestrator(world):
    url = await world.start_dashboard(with_orchestrator=True)

    async with httpx.AsyncClient() as client:
        response = await client.get(url + "/api/adr-conformance")

    assert response.status_code == 200
    assert isinstance(response.json(), dict)
