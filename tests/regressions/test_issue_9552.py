"""Regression pin for #9552: the thread-level event-loop freeze detector.

The #9556 lesson (its regression sibling in this directory) is that a
watchdog can be designed, referenced by memory notes, and never actually
delivered — silent non-delivery. These tests pin every runtime surface of
the #9552 detector so it cannot quietly disappear:

1. ``src/event_loop_watchdog.py`` exposes the public API;
2. ``HydraFlowConfig`` carries the three knobs with the contract defaults
   (detection ON, 120s threshold, hard-restart OFF — notify-default,
   restart-opt-in);
3. the knobs are System-tab editable (settings_registry), NOT env-table;
4. the orchestrator arms the watchdog in ``run()``;
5. the health monitor consumes the stall marker (the escalation half the
   thread itself cannot perform while the loop is frozen).
"""

from __future__ import annotations

import inspect


def test_module_exposes_public_api() -> None:
    import event_loop_watchdog as mod

    for symbol in (
        "EVENT_LOOP_STALL_EXIT_CODE",
        "EventLoopBeacon",
        "EventLoopWatchdog",
        "build_event_loop_watchdog",
        "event_loop_stall_marker_path",
        "read_stall_marker",
        "write_stall_marker",
        "clear_stall_marker",
    ):
        assert hasattr(mod, symbol), (
            f"event_loop_watchdog is missing `{symbol}` — the #9552 freeze "
            "detector's public contract regressed"
        )
    assert mod.EVENT_LOOP_STALL_EXIT_CODE == 75  # EX_TEMPFAIL, documented


def test_config_knobs_exist_with_contract_defaults() -> None:
    from config import HydraFlowConfig

    fields = HydraFlowConfig.model_fields
    assert "event_loop_watchdog_enabled" in fields
    assert "event_loop_watchdog_stall_seconds" in fields
    assert "event_loop_watchdog_hard_restart" in fields
    # Detection + dump + notify is default-ON; hard process restart is
    # default-OFF (branch-GC / external-liveness-watchdog precedent). A
    # flipped default here is a policy change, not a refactor.
    assert fields["event_loop_watchdog_enabled"].default is True
    assert fields["event_loop_watchdog_stall_seconds"].default == 120
    assert fields["event_loop_watchdog_hard_restart"].default is False


def test_knobs_are_settings_registry_entries_not_env() -> None:
    from settings_registry import SETTINGS

    for name in (
        "event_loop_watchdog_enabled",
        "event_loop_watchdog_stall_seconds",
        "event_loop_watchdog_hard_restart",
    ):
        assert name in SETTINGS, (
            f"`{name}` missing from settings_registry — the #9552 knobs are "
            "System-tab-editable by contract (knobs→System, never .env)"
        )


def test_orchestrator_arms_the_watchdog_in_run() -> None:
    from orchestrator import HydraFlowOrchestrator

    source = inspect.getsource(HydraFlowOrchestrator.run)
    assert "build_event_loop_watchdog" in source, (
        "HydraFlowOrchestrator.run no longer arms the event-loop freeze "
        "detector (#9552) — a synchronous block in any loop's _do_work "
        "would again freeze the whole fleet undetected"
    )
    assert ".stop()" in source


def test_health_monitor_consumes_the_stall_marker() -> None:
    from health_monitor_loop import HealthMonitorLoop

    assert hasattr(HealthMonitorLoop, "_check_event_loop_stall")
    # The escalation moved onto the heavy caretaker pass when the stall sweep
    # was decoupled onto its own fast cadence (#10652); scan both halves of
    # the cycle so the wiring is still asserted wherever it lives.
    source = inspect.getsource(HealthMonitorLoop._do_work) + inspect.getsource(
        HealthMonitorLoop._run_heavy_pass
    )
    assert "_check_event_loop_stall" in source, (
        "HealthMonitorLoop's cycle no longer runs the event-loop stall "
        "escalation check (#9552) — freeze markers would rot on disk "
        "unescalated"
    )
