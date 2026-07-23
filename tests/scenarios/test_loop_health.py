"""Registry-driven per-loop health harness (Part of #9854, v1 slice).

Every background loop registered in ``bg_loop_registry`` has a MockWorld
builder in ``tests/scenarios/catalog/loop_registrations._BUILDERS`` (enforced by
``catalog/test_catalog_completeness.py``). This harness parametrizes over that
same registry so it *cannot drift*: any loop added to the registry without a
builder reddens the completeness guard; any loop with a builder that crashes on
its first tick, or that fails to degrade gracefully when its primary port
raises, reddens this file.

Two contracts, one per loop, derived from the live registry:

Phase 1 — *does the thing*: drive one ``_do_work()`` tick against MockWorld
fakes and assert it returns a ``WorkCycleResult``-shaped value (``dict`` or
``None``) without raising. Catches the "loop crashes on first cycle" class that
previously broke ``flake_tracker`` / ``principles_audit`` /
``detector_calibration`` / ``fitness_scorecard`` in production (#9841) and was
only caught by a human eyeballing the dashboard.

Phase 2 — *fails soft*: poison the loop's primary port (``github``) so its first
call raises a transient ``RuntimeError``, drive one ``_execute_cycle()`` (the
base-class watchdog + error-reporting harness) and assert the loop survives —
no exception escapes and a terminal heartbeat status (``ok`` when it degrades
gracefully per-item, ``error`` when the whole cycle fails) is recorded, so a
broken loop is *visible* on the dashboard rather than silently wedged. This also
guards against a loop misclassifying a generic port fault as a fatal
auth/credit signal (which would crash-loop and burn attempt budget).

Both grandfather lists start EMPTY and are ratcheted: they may only shrink,
guarded by ``test_exemption_lists_only_shrink``. Phase-2 self-repair automation
(the actuator half) is out of scope for this slice — see the #9854 phase-2
checklist.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import execution
from base_background_loop import LoopDeps
from events import EventBus
from execution import SimpleResult
from runner_utils import AuthenticationRetryError
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import make_bg_loop_deps
from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog.loop_registrations import _BUILDERS, ensure_registered
from tests.scenarios.catalog.test_catalog_completeness import (
    _CATALOG_SKIP,
    _parse_bg_loop_registry,
)
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


# ---------------------------------------------------------------------------
# Grandfather lists — RATCHET: these may only SHRINK. See
# ``test_exemption_lists_only_shrink``. To add an entry you must raise its
# ceiling in the same diff (a deliberate, reviewed act) and justify it here.
# ---------------------------------------------------------------------------

#: Loops that genuinely cannot drive ``_do_work`` against bare MockWorld fakes.
_TICK_EXEMPT: frozenset[str] = frozenset()
_TICK_EXEMPT_CEILING = 0

#: Loops that legitimately propagate a primary-port fault instead of failing
#: soft (none today — the base loop catches every non-auth/credit exception).
_INJECT_EXEMPT: frozenset[str] = frozenset()
_INJECT_EXEMPT_CEILING = 0


_TICK_NAMES = sorted(set(_BUILDERS) - _TICK_EXEMPT)
_INJECT_NAMES = sorted(set(_BUILDERS) - _INJECT_EXEMPT)


@pytest.fixture(autouse=True)
def _ensure_registered() -> Iterator[None]:
    ensure_registered()
    yield


class _AirGappedRunner:
    """A ``SubprocessRunner`` that never spawns a real process.

    Several loops shell out to ``gh`` / ``git`` / ``make`` via
    ``subprocess_util.run_subprocess`` (which resolves ``get_default_runner()``).
    Left un-gapped the harness is non-hermetic — ``staging_promotion``'s ``gh pr
    list`` returns a real ``401 Bad credentials`` under a dev shell with stale
    creds, which ``subprocess_util`` classifies as a fatal ``AuthenticationError``
    and re-raises out of the tick. Return a benign non-zero result so
    ``run_subprocess`` raises a generic ``RuntimeError`` (the same shape as a gh
    404), which every loop already degrades past — deterministic, credential-
    independent, and no network.
    """

    async def run_simple(self, cmd: Any, **kwargs: Any) -> SimpleResult:
        return SimpleResult(
            stdout="", stderr="air-gapped by loop-health harness", returncode=1
        )

    async def create_streaming_process(self, cmd: Any, **kwargs: Any) -> Any:
        raise RuntimeError("air-gapped by loop-health harness")

    async def cleanup(self) -> None:
        return None


_AIRGAP_RUNNER = _AirGappedRunner()


@pytest.fixture(autouse=True)
def _airgap_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route every ``run_subprocess`` call through the air-gapped runner.

    ``run_subprocess`` calls ``get_default_runner()`` fresh each invocation, so
    patching it here air-gaps all module-qualified and bound-name callers alike.
    """
    monkeypatch.setattr(execution, "get_default_runner", lambda: _AIRGAP_RUNNER)


def _extra_ports(name: str) -> dict[str, Any]:
    """Per-loop ports a loop needs beyond the MockWorld base set to tick.

    Kept intentionally tiny — a big map here is a smell that the builder should
    supply the default instead. ``trust_fleet_sanity`` reads a separate
    ``event_bus`` handle for ``load_events_since`` (its builder defaults it to a
    bare ``MagicMock`` whose async method is not awaitable); a real
    ``EventBus`` gives an empty, awaitable history.
    """
    if name == "trust_fleet_sanity":
        return {"event_bus": EventBus()}
    return {}


class _FaultInjector:
    """Wrap a port so its FIRST method call raises once, then delegates.

    Faithful to "patch the primary port to raise once": the loop's first
    interaction with ``github`` fails with a transient ``RuntimeError`` (the
    shape of a gh 404 / network blip — NOT a code-bug type), after which the
    real fake behaves normally. Non-callable attribute access delegates
    unchanged so the port keeps its shape.
    """

    def __init__(self, target: Any) -> None:
        self._target = target
        self._tripped = False

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        if not callable(attr):
            return attr
        if asyncio.iscoroutinefunction(attr):

            async def _async_wrapped(*args: Any, **kwargs: Any) -> Any:
                if not self._tripped:
                    self._tripped = True
                    raise RuntimeError(f"injected fault on {name}()")
                return await attr(*args, **kwargs)

            return _async_wrapped

        def _sync_wrapped(*args: Any, **kwargs: Any) -> Any:
            if not self._tripped:
                self._tripped = True
                raise RuntimeError(f"injected fault on {name}()")
            return attr(*args, **kwargs)

        return _sync_wrapped


def _base_ports(world: MockWorld, github: Any) -> dict[str, Any]:
    """The MockWorld port set ``run_with_loops`` wires, with a chosen github."""
    return {
        "github": github,
        "workspace": world._workspace,
        "sentry": world._sentry,
        "clock": world._clock,
        "state": world._harness.state,
    }


def _loop_deps(tmp_path: Path, status_cb: Any) -> tuple[Any, LoopDeps]:
    """Fresh config + LoopDeps with an inspectable ``status_cb`` and no real sleep."""
    bg = make_bg_loop_deps(tmp_path)
    deps = LoopDeps(
        event_bus=bg.bus,
        stop_event=bg.stop_event,
        status_cb=status_cb,
        enabled_cb=bg.enabled_cb,
        sleep_fn=AsyncMock(),
    )
    return bg.config, deps


def _enable_kill_switch(config: Any, name: str) -> None:
    """Enable a loop's deploy-time kill-switch so its work path runs (as
    ``run_with_loops`` does), rather than short-circuiting to config_disabled."""
    flag = f"{name}_loop_enabled"
    if hasattr(config, flag):
        object.__setattr__(config, flag, True)


# ---------------------------------------------------------------------------
# Registry-drift guard (#9854 Phase 3): the health harness must cover every
# registered loop. Complements catalog/test_catalog_completeness with a
# health-specific failure message.
# ---------------------------------------------------------------------------


def test_health_harness_covers_bg_loop_registry() -> None:
    registry = _parse_bg_loop_registry()
    missing = registry - set(_BUILDERS) - _CATALOG_SKIP
    assert not missing, (
        f"Loops in bg_loop_registry with no per-loop health coverage: "
        f"{sorted(missing)}. Add a builder to "
        f"tests/scenarios/catalog/loop_registrations.py so the health harness "
        f"can drive them."
    )


def test_exemption_lists_only_shrink() -> None:
    known = set(_BUILDERS)
    stale_tick = _TICK_EXEMPT - known
    stale_inject = _INJECT_EXEMPT - known
    assert not stale_tick, (
        f"stale tick exemptions (not real loops): {sorted(stale_tick)}"
    )
    assert not stale_inject, (
        f"stale inject exemptions (not real loops): {sorted(stale_inject)}"
    )
    # Ratchet: adding an exemption requires bumping the ceiling in the same diff.
    assert len(_TICK_EXEMPT) <= _TICK_EXEMPT_CEILING, "tick exemption list grew"
    assert len(_INJECT_EXEMPT) <= _INJECT_EXEMPT_CEILING, "inject exemption list grew"


# ---------------------------------------------------------------------------
# Phase 1 — every registered loop drives one _do_work tick without crashing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _TICK_NAMES)
async def test_registered_loop_ticks(tmp_path: Path, name: str) -> None:
    world = MockWorld(tmp_path)
    extras = _extra_ports(name)
    if extras:
        # Pre-seed the full base set + extras so run_with_loops' warm-path
        # (which only refreshes github/workspace/state) can't drop sentry/clock.
        world._loop_ports = {**_base_ports(world, world.github), **extras}

    results = await world.run_with_loops([name], cycles=1)
    result = results[name]

    assert result is None or isinstance(result, dict), (
        f"{name}._do_work returned a non-WorkCycleResult "
        f"({type(result).__name__}); expected dict or None"
    )


# ---------------------------------------------------------------------------
# Phase 2 — every registered loop fails soft when its primary port raises.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _INJECT_NAMES)
async def test_registered_loop_survives_port_fault(tmp_path: Path, name: str) -> None:
    world = MockWorld(tmp_path)
    status_cb = MagicMock()
    config, deps = _loop_deps(tmp_path, status_cb)
    _enable_kill_switch(config, name)

    poison = _FaultInjector(world.github)
    ports = {**_base_ports(world, poison), **_extra_ports(name)}
    loop = LoopCatalog.instantiate(name, ports=ports, config=config, deps=deps)

    try:
        await loop._execute_cycle()
    except (AuthenticationError, CreditExhaustedError, AuthenticationRetryError) as exc:
        pytest.fail(
            f"{name}: a generic primary-port RuntimeError escaped _execute_cycle "
            f"as {type(exc).__name__} — the loop misclassified a transient fault "
            f"as a fatal auth/credit signal; it will crash-loop and burn budget."
        )

    statuses = [c.args[1] for c in status_cb.call_args_list if len(c.args) >= 2]
    assert statuses, (
        f"{name}: no heartbeat recorded after a port fault — the loop is "
        f"silently wedged (invisible on the dashboard) instead of failing soft."
    )
    assert statuses[-1] in {"ok", "error"}, (
        f"{name}: recorded a non-terminal heartbeat status {statuses[-1]!r}"
    )
