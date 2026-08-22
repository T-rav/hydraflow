"""Regression: the liveness kernel must not undo an operator's Stop (ADR-0135).

Failure mode (observed while arming ``install_liveness_watchdog.py --workspace``):
``POST /api/control/stop`` tears the orchestrator down, so
``GET /api/control/status`` reports ``"idle"`` — indistinguishable from a
freshly-booted, never-started factory. ``boot_guard.decide_boot_action`` treats
``idle`` on a verified-correct boot as STARTABLE, so the next 5-minute tick
issued ``POST /api/control/start`` and silently brought the factory back up
behind the operator's back. ``src/factory_autostart.py`` already honoured the
persisted ``operator_stopped`` latch (#11208); the kernel did not, because the
status API never exposed it.

Fix: ``ControlStatusResponse.operator_stopped`` carries the latch, and
``decide_boot_action(operator_stopped=True)`` turns a would-be START into
NO_ACTION. Two pins below, so the drift can never silently recur:

1. the exact post-Stop payload (idle + latch) through the kernel's real
   ``probe_boot_correctness`` composition yields NO_ACTION, never START;
2. the *pre-fix* payload shape (no ``operator_stopped`` key at all) still
   STARTs — the kernel fails open to its prior behaviour against an older
   factory, so this fix cannot regress down-recovery.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.liveness import boot_guard
from scripts.liveness.boot_guard import BootAction

_ORIGIN = "c" * 40


def _wire_verified_correct_boot(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    monkeypatch.setattr(boot_guard, "fetch_control_status", lambda *a, **k: payload)
    monkeypatch.setattr(boot_guard, "git_current_branch", lambda ws: "staging")
    monkeypatch.setattr(boot_guard, "git_origin_head", lambda ws, br: _ORIGIN)


def _probe() -> boot_guard.BootDecision:
    return boot_guard.probe_boot_correctness(
        workspace=Path("/tmp/ws"),
        factory_branch="staging",
        status_url="http://127.0.0.1:5555/api/control/status",
    )


def test_post_stop_idle_payload_with_latch_is_never_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire_verified_correct_boot(
        monkeypatch,
        {
            "status": "idle",
            "operator_stopped": True,
            "config": {"boot_sha": _ORIGIN, "commits_behind": 0},
        },
    )
    decision = _probe()
    assert decision.action is BootAction.NO_ACTION
    assert decision.action is not BootAction.START
    assert "operator stopped" in decision.reason


def test_pre_fix_payload_without_latch_field_still_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail-open: an older factory that never sends the field keeps the
    # existing verified-boot START path — the fix must not break recovery.
    _wire_verified_correct_boot(
        monkeypatch,
        {"status": "idle", "config": {"boot_sha": _ORIGIN, "commits_behind": 0}},
    )
    assert _probe().action is BootAction.START


def test_latch_cleared_by_start_restores_kernel_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Operator hits Start -> route clears the latch -> kernel may start again.
    _wire_verified_correct_boot(
        monkeypatch,
        {
            "status": "idle",
            "operator_stopped": False,
            "config": {"boot_sha": _ORIGIN, "commits_behind": 0},
        },
    )
    assert _probe().action is BootAction.START
