"""Fleet vitals — supervisor-level alarm engine, shadow-mode first (#11391).

Founding incident (2026-08-16): during the light-tier HITL cascade the
health monitor computed ``first_pass_rate=0.00 hitl_rate=0.74`` and logged
it at INFO while the fleet was sick — every individual run looked healthy,
so the per-run supervisor had nothing to judge. This engine gives the
fleet a verdict function: bands with ISA-18.2-style hysteresis (confirm
over K windows before alarming, re-arm below a lower threshold), a
mechanical suspect pass (correlate breach onset with the change ledger —
zero tokens), and a SHADOW intervention proposal from a closed menu.

Shadow discipline: this module never actuates. It produces one alarm per
episode carrying the diagnosis and the "would have done X" proposal; the
caller logs/escalates it. Actuators arm only after a calibration window
judges the shadow proposals (#11035 shadow-router pattern).

Pure: no I/O, no clock reads — callers pass readings, state, and change
events in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

#: Lookback for the mechanical suspect pass — changes older than this
#: before breach onset are not plausible proximate causes.
SUSPECT_LOOKBACK_HOURS = 24


#: Minimum real runs in the trend window before rate bands are trusted —
#: an IDLE factory reads first_pass_rate=0.0 with zero outcomes, which is
#: quiet, not sick (the cold-boot-noisy FP class; review BLOCKING).
MIN_RUNS_FOR_RATES = 5


@dataclass(frozen=True)
class FleetReading:
    """One health-monitor cycle's fleet-level metrics."""

    ts: datetime
    hitl_rate: float
    first_pass_rate: float
    run_count: int = MIN_RUNS_FOR_RATES  # callers SHOULD pass the real count


@dataclass(frozen=True)
class ChangeEvent:
    """One entry in the change ledger (merge, config flip, boot)."""

    ts: datetime
    kind: str  # "merge" | "config-flip" | "boot"
    ref: str  # sha / field name / boot sha
    description: str


@dataclass(frozen=True)
class FleetAlarm:
    band: str  # "hitl_rate" | "first_pass_rate"
    reading: FleetReading
    consecutive_breaches: int
    suspects: tuple[ChangeEvent, ...]
    shadow_proposal: str


@dataclass
class BandState:
    consecutive_breaches: int = 0
    alarm_active: bool = False


@dataclass
class FleetVitalsState:
    """Per-band hysteresis state. Serializable via ``to_dict``/``from_dict``."""

    bands: dict[str, BandState] = field(default_factory=dict)

    def band(self, name: str) -> BandState:
        return self.bands.setdefault(name, BandState())

    def to_dict(self) -> dict[str, Any]:
        return {
            name: {
                "consecutive_breaches": b.consecutive_breaches,
                "alarm_active": b.alarm_active,
            }
            for name, b in self.bands.items()
        }

    @classmethod
    def from_dict(cls, raw: Any) -> FleetVitalsState:
        state = cls()
        if not isinstance(raw, dict):
            return state
        for name, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            band = state.band(str(name))
            try:
                band.consecutive_breaches = int(entry.get("consecutive_breaches", 0))
            except (TypeError, ValueError):
                band.consecutive_breaches = 0
            band.alarm_active = bool(entry.get("alarm_active", False))
        return state


@dataclass(frozen=True)
class FleetBands:
    """Thresholds — sourced from config by the caller."""

    hitl_rate_alarm: float = 0.5
    hitl_rate_rearm: float = 0.3
    first_pass_floor: float = 0.05
    confirm_windows: int = 2


def _evaluate_band(
    band: BandState,
    *,
    breached: bool,
    cleared: bool,
    confirm_windows: int,
) -> bool:
    """Update *band* hysteresis; return True when a NEW alarm fires.

    - Breach must hold ``confirm_windows`` consecutive readings to alarm.
    - An active alarm re-arms (allowing a future alarm) only after the
      CLEAR condition holds — one alarm per episode, no flap.
    """
    if band.alarm_active:
        if cleared:
            band.alarm_active = False
            band.consecutive_breaches = 0
        return False
    if breached:
        band.consecutive_breaches += 1
        if band.consecutive_breaches >= confirm_windows:
            band.alarm_active = True
            return True
        return False
    band.consecutive_breaches = 0
    return False


def evaluate(
    state: FleetVitalsState,
    reading: FleetReading,
    *,
    bands: FleetBands,
    changes: list[ChangeEvent] | None = None,
) -> list[FleetAlarm]:
    """Feed one reading through every band; return newly-fired alarms.

    Mutates *state* (the caller persists it). ``changes`` feeds the
    suspect pass on the alarming reading only.
    """
    alarms: list[FleetAlarm] = []

    if reading.run_count < MIN_RUNS_FOR_RATES:
        # Too few real runs to trust any rate: reset streaks (a quiet
        # window is evidence of quiet, not of sickness) and never alarm.
        for name in ("hitl_rate", "first_pass_rate"):
            band = state.band(name)
            if not band.alarm_active:
                band.consecutive_breaches = 0
        return alarms

    hitl_band = state.band("hitl_rate")
    if _evaluate_band(
        hitl_band,
        breached=reading.hitl_rate >= bands.hitl_rate_alarm,
        cleared=reading.hitl_rate < bands.hitl_rate_rearm,
        confirm_windows=bands.confirm_windows,
    ):
        suspects = rank_suspects(reading.ts, changes or [])
        alarms.append(
            FleetAlarm(
                band="hitl_rate",
                reading=reading,
                consecutive_breaches=hitl_band.consecutive_breaches,
                suspects=suspects,
                shadow_proposal=shadow_proposal("hitl_rate", suspects),
            )
        )

    fp_band = state.band("first_pass_rate")
    if _evaluate_band(
        fp_band,
        breached=reading.first_pass_rate <= bands.first_pass_floor,
        cleared=reading.first_pass_rate > bands.first_pass_floor * 2,
        confirm_windows=bands.confirm_windows,
    ):
        suspects = rank_suspects(reading.ts, changes or [])
        alarms.append(
            FleetAlarm(
                band="first_pass_rate",
                reading=reading,
                consecutive_breaches=fp_band.consecutive_breaches,
                suspects=suspects,
                shadow_proposal=shadow_proposal("first_pass_rate", suspects),
            )
        )

    return alarms


def rank_suspects(
    onset: datetime, changes: list[ChangeEvent]
) -> tuple[ChangeEvent, ...]:
    """Mechanical suspect pass: recent changes before *onset*, newest first.

    Zero tokens — the newest-changed subsystem is the prime suspect (the
    founding incident's hitl_rate breach began minutes after the tiering
    boot). Config flips outrank merges at equal recency: a flipped flag is
    the cheaper hypothesis AND the cheaper revert.
    """
    lookback = onset - timedelta(hours=SUSPECT_LOOKBACK_HOURS)
    window = [c for c in changes if lookback <= c.ts <= onset]
    kind_rank = {"config-flip": 0, "boot": 1, "merge": 2}
    window.sort(key=lambda c: (-c.ts.timestamp(), kind_rank.get(c.kind, 3)))
    return tuple(window[:5])


def shadow_proposal(band: str, suspects: tuple[ChangeEvent, ...]) -> str:
    """Closed-menu intervention proposal — SHADOW ONLY, never actuated.

    The menu maps suspect kind → the reversible-by-construction control
    that already exists for it (ADR-0049 kill-switches, flag reverts,
    global pause). Rung-3 actuators will execute exactly these strings
    after the calibration window judges them.
    """
    if not suspects:
        return (
            f"SHADOW[{band}]: no change-ledger suspect in the lookback — "
            "would spawn one read-only fleet diagnostician, then default "
            "to global pause if its confidence is low."
        )
    prime = suspects[0]
    if prime.kind == "config-flip":
        return (
            f"SHADOW[{band}]: would revert config flip '{prime.ref}' "
            f"({prime.description})."
        )
    if prime.kind == "boot":
        return (
            f"SHADOW[{band}]: would flag boot {prime.ref} as suspect and "
            "disable feature flags introduced since the prior boot; "
            "rollback to last-known-good stays operator-gated (rung 4)."
        )
    return (
        f"SHADOW[{band}]: would disable the loop/flags introduced by "
        f"merge {prime.ref} ({prime.description}) via its ADR-0049 "
        "kill-switch."
    )
