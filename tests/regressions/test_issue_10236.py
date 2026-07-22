"""Regression #10236: staleness detector conflated poll cadence with cycle duration.

`TrustFleetSanityLoop.detect_staleness` computed its breach threshold as
`multiplier x interval_s`, where `interval_s` is the watched worker's own
poll interval (`BGWorkerManager.get_interval`). For `staging_bisect`, that
600s interval exists purely to check `StateTracker.last_rc_red_sha`
cheaply and often -- but the same `_do_work()` call can synchronously run
a red-SHA cycle (flake-probe reruns + `git bisect`) for up to
`staging_bisect_runtime_cap_seconds` (2700s default) before the heartbeat
next advances. `BaseBackgroundLoop._execute_cycle` only refreshes the
heartbeat at cycle *completion*, so a single legitimate cycle can run past
`multiplier * interval_s` while staying inside its own per-cycle watchdog
bound. That produced a false-positive `staleness` HITL escalation
(#10234): `elapsed_s=1310` against `threshold_s=1200`, while the live
`/api/trust/fleet` telemetry showed the loop completing normally minutes
later with zero tick errors.

Fix: floor the threshold at `interval_s + max_cycle_s`, sourcing
`max_cycle_s` from `BGWorkerManager.cycle_timeout(worker)` -- the loop's
own per-cycle watchdog bound, decoupled from its poll cadence.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.test_trust_fleet_sanity_loop import _loop, loop_env  # noqa: E402, F401


async def test_staging_bisect_mid_cycle_heartbeat_does_not_false_positive(
    loop_env,
) -> None:
    """Replays the exact #10234 incident numbers end-to-end through `_do_work`.

    interval_s=600 (staging_bisect_interval), elapsed_s=1310. Under the old
    `multiplier * interval_s` threshold (1200) this breached. max_cycle_s=2700
    here is a stand-in for `BGWorkerManager.cycle_timeout("staging_bisect")`
    (in production that resolves to `loop_watchdog_default_seconds`=7200s,
    since `StagingBisectLoop` doesn't override its per-cycle timeout — not
    `staging_bisect_runtime_cap_seconds`, which bounds one flake-probe/bisect
    sub-run, not the whole cycle). 2700 is a deliberately conservative
    floor for this test: the floored threshold (`600 + 2700 = 3300`) already
    clears 1310s, and the real 7200s bound clears it with even more margin.
    """
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    recent = (datetime.now(UTC) - timedelta(seconds=1310)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "staging_bisect": {"status": "ok", "last_run": recent, "details": {}},
    }
    bg_workers.worker_enabled = {"staging_bisect": True}
    bg_workers.get_interval.return_value = 600
    bg_workers.cycle_timeout.return_value = 2700

    async def fake_load(since):  # noqa: ARG001
        return []

    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)

    stats = await loop._do_work()

    assert stats["anomalies"] == 0
    pr.create_issue.assert_not_awaited()
