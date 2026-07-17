"""Parity test: every sandbox scenario must also pass in-process Tier 1.

If a scenario fails Tier 2 (sandbox) but passes here, the bug is in
container/wiring/UI. If both fail, the bug is in scenario logic or
Fake behavior.

A scenario may set ``IN_PROCESS = False`` to opt out of the in-process tier —
reserved for heavy, docker-only end-to-end flows whose many-loop convergence is
impractical (or hangs) in the fast in-process harness (e.g. s55's depth-2 nested
decomposition, which drives ~5 loops over a full multi-hop pipeline). Such
scenarios are excluded at collection (not skipped) so the guard against ignored
tests still holds for the rest.
"""

from __future__ import annotations

import pytest

from tests.sandbox_scenarios.runner.loader import load_all_scenarios

_IN_PROCESS_SCENARIOS = [
    s for s in load_all_scenarios() if getattr(s, "IN_PROCESS", True)
]


@pytest.mark.parametrize("scenario", _IN_PROCESS_SCENARIOS, ids=lambda s: s.NAME)
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
