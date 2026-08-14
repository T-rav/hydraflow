"""Guard: control/fleet.yaml covers the live loop fleet exactly (#10824).

The fleet register is only trustworthy if it can't drift from the
orchestrator's ``bg_loop_registry``. Key parity is enforced in BOTH
directions: a new loop must be classified before it ships (ADR-0120 Ruling
1 — nothing stays unclassified), and a removed loop must leave the register.
Uses the same AST parse of ``src/orchestrator.py`` the arch inventory
generator relies on, so this guard needs no orchestrator import.
"""

from __future__ import annotations

from pathlib import Path

from arch.generators.ai_system_inventory import _parse_bg_loop_registry
from control_register import load_fleet

_REPO_ROOT = Path(__file__).parent.parent


def test_fleet_register_matches_bg_loop_registry() -> None:
    live = set(_parse_bg_loop_registry(_REPO_ROOT / "src" / "orchestrator.py"))
    registered = set(load_fleet(_REPO_ROOT))

    unclassified = sorted(live - registered)
    stale = sorted(registered - live)
    assert not unclassified, (
        f"loop(s) {unclassified} exist in the orchestrator's bg_loop_registry "
        "but have no entry in control/fleet.yaml — classify them "
        "(error_driven / convertible / exploratory / infrastructure, ADR-0120 "
        "Ruling 1). A loop nobody classified is a loop nobody decided has or "
        "hasn't a setpoint."
    )
    assert not stale, (
        f"entry(ies) {stale} in control/fleet.yaml no longer exist in the "
        "orchestrator's bg_loop_registry — remove them so the register stays "
        "an honest census (it feeds ADR-0133's instrument count)."
    )
