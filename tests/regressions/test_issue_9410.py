"""Regression for issue #9410 — trust_fleet_sanity silent (dead-man-switch).

Issue #9410 was auto-filed by the `health_monitor` dead-man-switch:

    sanity-loop-stalled: trust_fleet_sanity silent for 520220s (threshold 1800s)

The dead-man-switch itself works (see tests/test_health_monitor_sanity_stall.py)
— it fired because `TrustFleetSanityLoop` genuinely stopped ticking. This test
reproduces a concrete code path by which that loop silently stalls *forever*:

`TrustFleetSanityLoop._do_work()` calls `_reconcile_closed_escalations()` as the
very first awaited step (src/trust_fleet_sanity_loop.py:201). That method shells
out to `gh issue list` and awaits `proc.communicate()` with **no timeout**
(src/trust_fleet_sanity_loop.py:401-406). If `gh` blocks — auth prompt, a
network black-hole, a wedged child — the await never returns, so:

  * the work cycle never reaches `set_trust_fleet_sanity_last_run()` (line 331),
    so the heartbeat freezes at the moment of the hang ("silent for N seconds");
  * the orchestrator supervisor wakes only on task *completion*
    (`asyncio.wait(..., FIRST_COMPLETED)`, src/orchestrator.py), never on a
    *hung* task, so the dead loop is never restarted — matching the playbook's
    only remedy, "restart the orchestrator".

Desired behavior: a stuck subprocess must be bounded (e.g. `asyncio.wait_for`)
so the cycle still finishes and the heartbeat keeps advancing. This test asserts
that bounded behavior and is RED against current code (it hangs).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import trust_fleet_sanity_loop
from config import HydraFlowConfig
from trust_fleet_sanity_loop import TrustFleetSanityLoop

# Generous relative to any sane subprocess timeout, tiny relative to the loop's
# 600s interval: if the cycle isn't bounded, it never returns and we trip this.
_CYCLE_BOUND_SECONDS = 3.0


class _HangingProcess:
    """Stand-in for an `asyncio` subprocess whose `gh` child never returns."""

    returncode = 0
    killed = False

    def kill(self) -> None:
        # The bounded caller SIGKILLs the wedged child on timeout so it doesn't
        # leak; the stub just records that it happened.
        self.killed = True

    async def communicate(self) -> tuple[bytes, bytes]:
        # Model a wedged `gh issue list` — block effectively forever. A bounded
        # caller (the fix) cancels this via its own timeout; the unbounded
        # caller (current code) waits here until the heat death of the universe.
        await asyncio.sleep(1_000_000)
        return b"[]", b""


async def _hanging_create_subprocess_exec(
    *args: object, **kwargs: object
) -> _HangingProcess:
    del args, kwargs
    return _HangingProcess()


def _make_loop(tmp_path: Path) -> TrustFleetSanityLoop:
    # __new__ bypasses the ctor (which needs a full LoopDeps + collaborators);
    # `_reconcile_closed_escalations` only reads `_config.repo` before the hang.
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        trust_fleet_sanity_interval=600,
    )
    loop = TrustFleetSanityLoop.__new__(TrustFleetSanityLoop)
    loop._config = cfg
    return loop


@pytest.mark.asyncio
async def test_reconcile_does_not_hang_when_gh_subprocess_stalls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        _hanging_create_subprocess_exec,
    )
    # Shrink the production subprocess cap so the bounded path fires fast — the
    # fix's real 30s timeout would itself blow the 3s cycle bound below. We are
    # asserting the call is *bounded*, not the magnitude of the bound.
    monkeypatch.setattr(trust_fleet_sanity_loop, "_RECONCILE_GH_TIMEOUT_SECONDS", 0.05)
    loop = _make_loop(tmp_path)

    try:
        await asyncio.wait_for(
            loop._reconcile_closed_escalations(),
            timeout=_CYCLE_BOUND_SECONDS,
        )
    except TimeoutError:
        pytest.fail(
            "BUG #9410: _reconcile_closed_escalations() never returned — "
            "`proc.communicate()` has no timeout, so a stuck `gh issue list` "
            "stalls the whole trust_fleet_sanity cycle indefinitely. The "
            "heartbeat freezes and the dead-man-switch trips "
            "('trust_fleet_sanity silent for N seconds')."
        )
