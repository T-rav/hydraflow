"""Boot-smoke: every loop on ServiceRegistry ticks once without an unexpected raise.

Closes the gap between "unit tests + CI green" and "the loops actually run when
the server boots in production".  Tonight's cascade had five distinct loop-runtime
failures (``JSONDecodeError`` on audit-json, ``issue #0`` sentinel mis-handling,
ADR title drift, missing-label gh failures, LiveCorpusReplayLoop wiring) and only
the wiring one was caught by static tests.

The smoke contract is intentionally permissive: a loop is allowed to fail at the
external-IO boundary (``subprocess`` returning rc!=0 for a missing ``gh`` binary,
``ConnectionError`` reaching the real GitHub API, etc.) because that's expected
when test-mode mocks aren't wired.  It is **not** allowed to raise on the
internal contract — ``TypeError`` from a missing attribute, ``json.JSONDecodeError``
from parsing tool output, ``KeyError`` from a stale dict shape — that's the
signature of a bug like the ones tonight surfaced.

Tradeoff: tick-once misses multi-cycle bugs (dedup races, attempt counters,
state-machine progression).  Those still need targeted scenario tests.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus
from service_registry import (
    ServiceRegistry,
    WorkerRegistryCallbacks,
    build_services,
)
from state import StateTracker
from tests.test_service_registry import _make_callbacks

if TYPE_CHECKING:
    from config import HydraFlowConfig


# Failure modes that mean "external IO unavailable in the test box", not "bug":
#   - subprocess called something that's not on PATH or returned rc!=0
#   - real network call hit a DNS/socket error
#   - filesystem permissions / missing path
_EXPECTED_EXTERNAL_FAILURES: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    PermissionError,
    FileNotFoundError,
)


def _all_loop_fields() -> list[str]:
    """Return every ServiceRegistry dataclass field ending in ``_loop``."""
    return [f for f in ServiceRegistry.__dataclass_fields__ if f.endswith("_loop")]


@pytest.mark.asyncio
@pytest.mark.parametrize("loop_field", _all_loop_fields())
async def test_loop_ticks_without_internal_raise(
    config: HydraFlowConfig, loop_field: str
) -> None:
    """``await loop._do_work()`` must not raise an internal-contract error.

    External-IO failures (``ConnectionError`` etc.) are tolerated — they mean
    the loop reached its boundary and a real fake would be needed to drive it
    further.  Anything else is a wiring / sentinel / parse bug, which is
    exactly what this smoke catches.
    """
    bus = EventBus()
    state = StateTracker(config.state_file)
    stop_event = asyncio.Event()
    callbacks = _make_callbacks()

    registry = build_services(config, bus, state, stop_event, callbacks)
    loop = getattr(registry, loop_field)
    assert loop is not None, f"{loop_field} is gated off by config"

    try:
        await asyncio.wait_for(loop._do_work(), timeout=10.0)
    except _EXPECTED_EXTERNAL_FAILURES:
        # Boundary reached; that's the contract.
        pass
    except RuntimeError as exc:
        # ``RuntimeError`` is the generic wrapper that ``subprocess_util`` and
        # ``execution.SubprocessRunner`` raise for non-zero subprocess exits.
        # We allow it iff the message smells like an external-IO failure;
        # otherwise re-raise so the test fails with the real traceback.
        if any(
            marker in str(exc).lower()
            for marker in (
                "command",
                "rc=",
                "exit",
                "not found",
                "could not resolve",
                "permission denied",
            )
        ):
            pass
        else:
            raise
    except TimeoutError as exc:
        raise AssertionError(
            f"{loop_field} ticked beyond 10s; mock the boundary for a deterministic smoke"
        ) from exc


def _disabled_callbacks() -> WorkerRegistryCallbacks:
    """Callbacks with every worker's kill switch OFF."""
    return WorkerRegistryCallbacks(
        update_status=lambda *args, **kwargs: None,
        is_enabled=lambda name: False,
        get_interval=lambda name: 60,
        get_watchdog_timeout=lambda name: 7200,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loop_field", _all_loop_fields())
async def test_loop_honours_its_kill_switch(
    config: HydraFlowConfig, loop_field: str
) -> None:
    """Every registry loop short-circuits on `enabled_cb`, by reference (#11548).

    ADR-0049's convention: gate `_do_work` on `self._enabled_cb(self._worker_name)`
    at the top and return `{"status": "disabled"}`. Verified per loop, by hand,
    in each loop's own test file until now — which is opt-in: a new loop is
    covered only if its author remembers to write the test. Sweeping the
    registry makes it structural.

    The wiki suggests verifying this with
    `grep -L 'self._enabled_cb' src/*_loop.py`. That checks the SPELLING. This
    calls `_do_work` with the switch off and checks what the loop DOES — one
    that reads `_enabled_cb` and ignores the answer passes the grep and fails
    here.

    How many loops were previously uncovered is deliberately not claimed: a
    filename predicate and a class-mention predicate answer it in opposite
    directions (nine versus zero), which is the argument for an executable
    sweep rather than another grep.
    """
    bus = EventBus()
    state = StateTracker(config.state_file)
    stop_event = asyncio.Event()

    registry = build_services(config, bus, state, stop_event, _disabled_callbacks())
    loop = getattr(registry, loop_field)
    assert loop is not None, f"{loop_field} is gated off by config"

    result = await asyncio.wait_for(loop._do_work(), timeout=10.0)

    assert result == {"status": "disabled"}, (
        f"{loop_field} did not short-circuit with its kill switch off — it "
        f"returned {result!r}. ADR-0049: gate `_do_work` on "
        f"`self._enabled_cb(self._worker_name)` at the TOP and return "
        f'{{"status": "disabled"}}. A loop that runs while disabled ignores '
        f"the operator's bg-worker control."
    )
