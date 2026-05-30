"""Parametrized sandbox-scenario runner.

The scenario harness CLI invokes this with -k or specific test ID; each
scenario module's assert_outcome is called with (api, page) fixtures.
"""

from __future__ import annotations

import os

import pytest

from tests.sandbox_scenarios.runner.loader import load_all_scenarios

# Filter out s00_smoke — that's parity-only (no assert_outcome). When the
# harness selects one scenario, filter parametrization before collection so
# pytest does not report the rest of the catalog as skipped tests.
_ALL_SCENARIOS = [s for s in load_all_scenarios() if hasattr(s, "assert_outcome")]
_ONLY = os.environ.get("SCENARIO_NAME")
_SCENARIOS = [s for s in _ALL_SCENARIOS if not _ONLY or s.NAME == _ONLY]


if _SCENARIOS:

    @pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.NAME)
    @pytest.mark.asyncio
    async def test_scenario(scenario, api, page) -> None:
        """Run scenario.assert_outcome with the API client + Playwright page."""
        await scenario.assert_outcome(api, page)

else:

    def test_scenario_catalog_selection_is_valid() -> None:
        """Fail loudly when the sandbox catalog or SCENARIO_NAME is empty."""
        if _ONLY:
            raise AssertionError(f"SCENARIO_NAME={_ONLY!r} did not match any scenario")
        raise AssertionError("No Tier-2 scenarios with assert_outcome were discovered")
