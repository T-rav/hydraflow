"""THE calibration fixture (#11391): the 2026-08-16 founding incident.

At 16:00Z, mid light-tier cascade, the health monitor logged
``first_pass_rate=0.00 ... hitl_rate=0.74`` at INFO and nothing alarmed.
The engine MUST, replayed that exact reading:
1. Alarm on both bands (after the confirm window),
2. Rank the tiering merge — the newest change before onset — as the
   prime suspect,
3. Shadow-propose disabling it via its kill-switch (the intervention a
   human performed ~3 hours later).
If the machinery cannot pass its own founding incident, it does not ship.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fleet_vitals import (
    ChangeEvent,
    FleetBands,
    FleetReading,
    FleetVitalsState,
    evaluate,
)

ONSET = datetime(2026, 8, 16, 16, 0, 0, tzinfo=UTC)
INCIDENT = FleetReading(ts=ONSET, hitl_rate=0.74, first_pass_rate=0.0, run_count=25)
LEDGER = [
    ChangeEvent(
        ONSET - timedelta(hours=8, minutes=25),
        "merge",
        "d2aaa1daf",
        "feat(planner): size-tiered planning (#11305)",
    ),
    ChangeEvent(
        ONSET - timedelta(hours=20),
        "merge",
        "d8584d733",
        "feat(plan-review): delta re-review (#11301)",
    ),
]


def test_founding_incident_alarms_names_suspect_and_proposes() -> None:
    state = FleetVitalsState()
    bands = FleetBands()
    first = evaluate(state, INCIDENT, bands=bands, changes=LEDGER)
    assert first == []  # confirm discipline: one reading is not an episode
    alarms = evaluate(state, INCIDENT, bands=bands, changes=LEDGER)
    fired = {a.band for a in alarms}
    assert fired == {"hitl_rate", "first_pass_rate"}
    for alarm in alarms:
        assert alarm.suspects[0].ref == "d2aaa1daf"
        assert "SHADOW" in alarm.shadow_proposal
        assert "d2aaa1daf" in alarm.shadow_proposal
        assert "kill-switch" in alarm.shadow_proposal
