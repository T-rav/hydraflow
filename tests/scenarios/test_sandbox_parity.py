"""Parity test: every sandbox scenario must also pass in-process Tier 1.

If a scenario fails Tier 2 (sandbox) but passes here, the bug is in
container/wiring/UI. If both fail, the bug is in scenario logic or
Fake behavior.
"""

from __future__ import annotations

import pytest

from tests.sandbox_scenarios.runner.loader import load_all_scenarios


@pytest.mark.parametrize("scenario", load_all_scenarios(), ids=lambda s: s.NAME)
@pytest.mark.asyncio
async def test_sandbox_scenario_runs_in_process(mock_world, scenario) -> None:
    seed = scenario.seed()
    mock_world.apply_seed(seed)

    if seed.loops_enabled is None:
        result = await mock_world.run_pipeline()
        if result._outcomes:
            advanced = any(
                outcome.final_stage != "triage" for outcome in result._outcomes.values()
            )
            assert advanced, f"scenario {scenario.NAME} produced no pipeline progress"
        return

    stats = await mock_world.run_with_loops(
        seed.loops_enabled, cycles=seed.cycles_to_run
    )
    assert stats, f"scenario {scenario.NAME} produced no loop stats"
