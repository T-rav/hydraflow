"""Factory autostart config flag + operator-stopped latch (#11208).

``make factory`` (and the launchd liveness relaunch) previously only brought
up the dashboard/server — the runtime booted ``running:false`` and an
operator had to remember ``POST /api/control/start``. These tests cover the
config flag + persisted latch that let ``server.py`` autostart the host
orchestrator at boot, unless the operator explicitly stopped it last.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from events import EventBus, EventType
from tests.helpers import make_tracker


def _cfg(tmp_path: Path, **over: object) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        **over,
    )


def test_factory_autostart_defaults_true(tmp_path: Path) -> None:
    assert _cfg(tmp_path).factory_autostart is True


def test_factory_autostart_explicit_false(tmp_path: Path) -> None:
    assert _cfg(tmp_path, factory_autostart=False).factory_autostart is False


def test_factory_autostart_env_override_false(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_FACTORY_AUTOSTART", "false")
    assert _cfg(tmp_path).factory_autostart is False


def test_factory_autostart_env_override_true(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_FACTORY_AUTOSTART", "true")
    assert _cfg(tmp_path).factory_autostart is True


# ---------------------------------------------------------------------------
# operator_stopped latch — persisted so a deliberate Stop survives relaunch.
# ---------------------------------------------------------------------------


def test_operator_stopped_defaults_false(tmp_path: Path) -> None:
    tracker = make_tracker(tmp_path)
    assert tracker.get_operator_stopped() is False


def test_operator_stopped_round_trips(tmp_path: Path) -> None:
    tracker = make_tracker(tmp_path)
    tracker.set_operator_stopped(True)
    assert tracker.get_operator_stopped() is True
    tracker.set_operator_stopped(False)
    assert tracker.get_operator_stopped() is False


def test_operator_stopped_persists_across_reload(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    tracker = make_tracker(tmp_path, filename=state_file.name)
    tracker.set_operator_stopped(True)

    from state import StateTracker

    reloaded = StateTracker(state_file)
    assert reloaded.get_operator_stopped() is True


# ---------------------------------------------------------------------------
# decide_autostart — pure latch/flag matrix (#11208)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory_autostart", "operator_stopped", "already_running", "expected"),
    [
        # Autostart enabled, no operator stop, not running -> starts.
        (True, False, False, True),
        # Operator explicitly stopped last -> latch wins, never starts.
        (True, True, False, False),
        # Flag disabled -> never starts, regardless of latch.
        (False, False, False, False),
        (False, True, False, False),
        # Already running -> never redundantly starts, regardless of flags.
        (True, False, True, False),
        (True, True, True, False),
        (False, False, True, False),
        (False, True, True, False),
    ],
)
def test_decide_autostart_matrix(
    factory_autostart: bool,
    operator_stopped: bool,
    already_running: bool,
    expected: bool,
) -> None:
    from factory_autostart import decide_autostart

    decision = decide_autostart(
        factory_autostart=factory_autostart,
        operator_stopped=operator_stopped,
        already_running=already_running,
    )
    assert decision.should_start is expected
    assert decision.reason  # always a non-empty explanation


def test_decide_autostart_operator_latch_beats_enabled_flag() -> None:
    """The operator-stopped latch wins even when factory_autostart is True —
    deliberate downtime must stay down until the operator hits Start again."""
    from factory_autostart import decide_autostart

    decision = decide_autostart(
        factory_autostart=True, operator_stopped=True, already_running=False
    )
    assert decision.should_start is False
    assert "operator" in decision.reason.lower()


# ---------------------------------------------------------------------------
# maybe_autostart_host — thin async I/O edge over decide_autostart
# ---------------------------------------------------------------------------


def _cfg_with_autostart(tmp_path: Path, *, factory_autostart: bool) -> HydraFlowConfig:
    return _cfg(tmp_path, factory_autostart=factory_autostart)


def _fake_host_runtime(*, running: bool) -> SimpleNamespace:
    return SimpleNamespace(running=running, start=AsyncMock(), orchestrator=MagicMock())


@pytest.mark.asyncio
async def test_maybe_autostart_host_starts_when_eligible(tmp_path: Path) -> None:
    from factory_autostart import maybe_autostart_host

    config = _cfg_with_autostart(tmp_path, factory_autostart=True)
    state = make_tracker(tmp_path)
    bus = EventBus()
    host = _fake_host_runtime(running=False)

    started = await maybe_autostart_host(
        config=config, host_runtime=host, state=state, event_bus=bus
    )

    assert started is True
    host.start.assert_awaited_once()
    published = [
        e for e in bus.get_history() if e.type == EventType.ORCHESTRATOR_STATUS
    ]
    assert len(published) == 1
    assert published[0].data["status"] == "running"


@pytest.mark.asyncio
async def test_maybe_autostart_host_reenables_disabled_pipeline_workers(
    tmp_path: Path,
) -> None:
    """Autostart mirrors operator Start (#11611): a host that boots with its
    pipeline workers disabled has no path from the board to READY. The latch
    never gates this — an operator kill-switch on `plan` leaves it False."""
    from factory_autostart import maybe_autostart_host

    config = _cfg_with_autostart(tmp_path, factory_autostart=True)
    state = make_tracker(tmp_path)
    state.set_disabled_workers({"plan", "triage", "principles_audit"})
    host = _fake_host_runtime(running=False)

    await maybe_autostart_host(
        config=config, host_runtime=host, state=state, event_bus=EventBus()
    )

    assert state.get_disabled_workers() == {"principles_audit"}


@pytest.mark.asyncio
async def test_maybe_autostart_host_flips_the_orchestrators_enabled_flags(
    tmp_path: Path,
) -> None:
    from factory_autostart import maybe_autostart_host

    config = _cfg_with_autostart(tmp_path, factory_autostart=True)
    state = make_tracker(tmp_path)
    state.set_disabled_workers({"plan"})
    host = _fake_host_runtime(running=False)

    await maybe_autostart_host(
        config=config, host_runtime=host, state=state, event_bus=EventBus()
    )

    host.orchestrator.set_bg_worker_enabled.assert_called_once_with("plan", True)


@pytest.mark.asyncio
async def test_maybe_autostart_host_skips_when_operator_stopped(
    tmp_path: Path,
) -> None:
    from factory_autostart import maybe_autostart_host

    config = _cfg_with_autostart(tmp_path, factory_autostart=True)
    state = make_tracker(tmp_path)
    state.set_operator_stopped(True)
    bus = EventBus()
    host = _fake_host_runtime(running=False)

    started = await maybe_autostart_host(
        config=config, host_runtime=host, state=state, event_bus=bus
    )

    assert started is False
    host.start.assert_not_called()
    assert bus.get_history() == []


@pytest.mark.asyncio
async def test_maybe_autostart_host_skips_when_flag_disabled(tmp_path: Path) -> None:
    from factory_autostart import maybe_autostart_host

    config = _cfg_with_autostart(tmp_path, factory_autostart=False)
    state = make_tracker(tmp_path)
    bus = EventBus()
    host = _fake_host_runtime(running=False)

    started = await maybe_autostart_host(
        config=config, host_runtime=host, state=state, event_bus=bus
    )

    assert started is False
    host.start.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_autostart_host_skips_when_already_running(
    tmp_path: Path,
) -> None:
    from factory_autostart import maybe_autostart_host

    config = _cfg_with_autostart(tmp_path, factory_autostart=True)
    state = make_tracker(tmp_path)
    bus = EventBus()
    host = _fake_host_runtime(running=True)

    started = await maybe_autostart_host(
        config=config, host_runtime=host, state=state, event_bus=bus
    )

    assert started is False
    host.start.assert_not_called()
