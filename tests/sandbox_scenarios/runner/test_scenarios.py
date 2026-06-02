"""Parametrized sandbox-scenario runner.

The scenario harness CLI invokes this with -k or specific test ID; each
scenario module's assert_outcome is called with (api, page) fixtures.
"""

from __future__ import annotations

import os

import pytest

from tests.sandbox_scenarios.runner.loader import load_all_scenarios

# Filter out s00_smoke — that's parity-only (no assert_outcome).
_SCENARIOS = [s for s in load_all_scenarios() if hasattr(s, "assert_outcome")]
_ONLY = os.environ.get("SCENARIO_NAME")
if _ONLY:
    _SCENARIOS = [s for s in _SCENARIOS if s.NAME == _ONLY]


if _SCENARIOS:

    @pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.NAME)
    @pytest.mark.asyncio
    async def test_scenario(scenario, api, page) -> None:
        """Run scenario.assert_outcome with the API client + Playwright page."""
        await scenario.assert_outcome(api, page)

else:

    def test_no_scenarios_registered_fails_closed() -> None:
        """Fail closed when the requested runnable scenario does not exist."""
        if _ONLY:
            pytest.fail(f"SCENARIO_NAME={_ONLY!r} has no runnable scenario")
        pytest.fail("No Tier-2 scenarios with assert_outcome are registered")
