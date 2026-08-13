"""Control register — fleet classification + human-signed setpoints (#10824).

ADR-0120 Ruling 1 classified the loop fleet (already error-driven / convertible
/ irreducibly exploratory) in prose only; nothing machine-readable existed, so
neither the setpoint conversion (#10824), the vitals-methodology instrument
count (ADR-0133's ``widened_sigma_multiplier(n)``), nor the innovation-sensing
R-join (#10825 rung 3) had a registry to key on. This module is that registry.

Two YAML files, versioned in-repo under ``control/``:

- ``fleet.yaml`` — one entry per ``worker_name`` in the orchestrator's
  ``bg_loop_registry``, carrying its :class:`ControlClass`. Guard-tested for
  exact key parity with the live registry (both directions).
- ``setpoints.yaml`` — per-loop :class:`SetpointSpec`. **An unsigned setpoint
  is inert**: the machine may propose values from history, never self-assign
  them (envelope discipline, ADR-0120; ``docs/wiki/terms/setpoint.md`` — "a
  live, human-signed target a regulator reads each cycle"). Signing is a
  human editing ``signed_by``/``signed_date`` in the YAML.

The regulator assembly (:func:`regulate`) is the deadband + hysteresis stage
of the per-loop chain in #10824: error = PV − SP, a band absorbing normal
noise, and Schmitt-style hysteresis so quiescence doesn't flap at the band
edge. This is the first production instantiation of
``signal_control.SchmittHysteresis`` (ADR-0120 named its dormancy explicitly).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from signal_control import SchmittHysteresis

logger = logging.getLogger("hydraflow.control_register")

CONTROL_DIR = "control"
FLEET_FILENAME = "fleet.yaml"
SETPOINTS_FILENAME = "setpoints.yaml"


class ControlClass(StrEnum):
    """ADR-0120 Ruling 1 buckets, machine-readable."""

    #: Already regulates against a baseline/budget — has a zero.
    ERROR_DRIVEN = "error_driven"
    #: Finding-driven today, but a plant PV exists — conversion candidate.
    CONVERTIBLE = "convertible"
    #: Novelty has no setpoint; takes meta-setpoints (rate budgets) only.
    EXPLORATORY = "exploratory"
    #: Plumbing/actuators — not a sensor; regulation does not apply.
    INFRASTRUCTURE = "infrastructure"


@dataclass(frozen=True)
class FleetEntry:
    worker_name: str
    control_class: ControlClass
    #: Human description of the process variable, for convertible/error-driven.
    pv: str = ""
    #: Join key into finder calibration (#10821) for the innovation R (#10825).
    finder_id: str = ""
    notes: str = ""


@dataclass(frozen=True)
class SetpointSpec:
    """A per-loop setpoint. Inert until a human signs it."""

    worker_name: str
    pv: str
    units: str
    #: The target. Machine-proposed values live here too — inert while unsigned.
    value: float
    #: Deadband half-width in PV units: |error| <= band is "at setpoint".
    band: float
    #: Which side of the setpoint is healthy. "above": PV >= value is in-band.
    direction: str = "above"
    #: Empty string = unsigned = the regulator MUST NOT act on this spec.
    signed_by: str = ""
    signed_date: str = ""
    #: The ADR/issue that makes this number an obligation, not a preference.
    authority: str = ""

    @property
    def active(self) -> bool:
        return bool(self.signed_by.strip())


@dataclass(frozen=True)
class RegulatorVerdict:
    """One regulation cycle's output for a converted loop."""

    pv: float
    error: float
    quiescent: bool
    #: False when the spec was unsigned/absent — caller keeps legacy behavior.
    regulated: bool


def load_fleet(repo_root: Path) -> dict[str, FleetEntry]:
    """Load ``control/fleet.yaml``. Raises on malformed entries — the fleet
    file is repo-versioned and guard-tested, so failure here is a CI bug,
    not an operational condition to paper over (fail-closed per Port rules).
    """
    path = repo_root / CONTROL_DIR / FLEET_FILENAME
    raw = yaml.safe_load(path.read_text()) or {}
    fleet: dict[str, FleetEntry] = {}
    for worker_name, entry in raw.items():
        data = entry or {}
        fleet[worker_name] = FleetEntry(
            worker_name=worker_name,
            control_class=ControlClass(data["class"]),
            pv=str(data.get("pv", "")),
            finder_id=str(data.get("finder_id", "")),
            notes=str(data.get("notes", "")),
        )
    return fleet


def load_setpoints(repo_root: Path) -> dict[str, SetpointSpec]:
    """Load ``control/setpoints.yaml``; missing file = no setpoints (inert)."""
    path = repo_root / CONTROL_DIR / SETPOINTS_FILENAME
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    specs: dict[str, SetpointSpec] = {}
    for worker_name, entry in raw.items():
        data = entry or {}
        try:
            band = float(data["band"])
            if band <= 0:
                # A setpoint without a deadband is not a regulator assembly
                # (ADR-0120: "deadband + hysteresis on the error") — refuse it.
                raise ValueError(f"band must be > 0, got {band}")
            specs[worker_name] = SetpointSpec(
                worker_name=worker_name,
                pv=str(data.get("pv", "")),
                units=str(data.get("units", "")),
                value=float(data["value"]),
                band=band,
                direction=str(data.get("direction", "above")),
                signed_by=str(data.get("signed_by") or ""),
                signed_date=str(data.get("signed_date") or ""),
                authority=str(data.get("authority", "")),
            )
        except (KeyError, TypeError, ValueError):
            # A malformed setpoint must never activate a regulator; skip it
            # loudly. (Unsigned-but-well-formed specs load fine and stay inert
            # via .active — this branch is for structural damage only.)
            logger.warning(
                "control_register: malformed setpoint for %r ignored", worker_name
            )
    return specs


def setpoint_for(repo_root: Path, worker_name: str) -> SetpointSpec | None:
    """Convenience: the (possibly unsigned) spec for one loop, or None."""
    return load_setpoints(repo_root).get(worker_name)


def regulate(
    pv: float, spec: SetpointSpec | None, *, previously_quiescent: bool
) -> RegulatorVerdict:
    """One cycle of the regulator assembly: error, deadband, hysteresis.

    Quiescence ENTERS only when the PV reaches the setpoint itself and EXITS
    only when the error leaves the deadband — the Schmitt gap between those
    two thresholds is what stops flapping at the band edge. Callers persist
    ``quiescent`` across cycles and feed it back as ``previously_quiescent``;
    losing that state (e.g. a loop restart) safely re-enters the acting mode.

    An absent or unsigned spec returns ``regulated=False`` with ``error=0`` —
    the caller MUST keep its legacy (finding-driven) behavior in that case.
    """
    if spec is None or not spec.active:
        return RegulatorVerdict(pv=pv, error=0.0, quiescent=False, regulated=False)

    sign = 1.0 if spec.direction == "above" else -1.0
    # error > 0 means "PV on the unhealthy side of the setpoint".
    error = sign * (spec.value - pv)

    # Health margin = -error: >= 0 at/above setpoint, <= -band out of the
    # deadband. Quiescence trips at margin >= 0 and clears only at margin <=
    # -band — the Schmitt gap between the two is the anti-flap. The gate is
    # stateless across cycles here, so prior quiescence is replayed through
    # the public API with one priming update at the trip threshold.
    gate = SchmittHysteresis(trip_high=0.0, clear_low=-spec.band)
    if previously_quiescent:
        gate.update(0.0)
    quiescent = gate.update(-error)
    return RegulatorVerdict(pv=pv, error=error, quiescent=quiescent, regulated=True)


def fleet_counts(fleet: dict[str, FleetEntry]) -> dict[ControlClass, int]:
    """Per-class census — the real ``n`` ADR-0133's multiplicity math awaits."""
    counts = dict.fromkeys(ControlClass, 0)
    for entry in fleet.values():
        counts[entry.control_class] += 1
    return counts


def measurement_noise_for(
    worker_name: str,
    fleet: dict[str, FleetEntry],
    floors: dict[str, object],
) -> float | None:
    """The #10825 rung-3 R-join: a loop's Kalman measurement noise from its
    calibrated finder floor (#10821). Returns ``floor_sigma`` for the fleet
    entry's ``finder_id``, or None when the loop has no finder join or the
    finder is uncalibrated — callers must treat None as "cannot sense", never
    substitute a fabricated variance.
    """
    entry = fleet.get(worker_name)
    if entry is None or not entry.finder_id:
        return None
    floor = floors.get(entry.finder_id)
    if floor is None:
        return None
    sigma = getattr(floor, "floor_sigma", None)
    return float(sigma) if sigma is not None else None
