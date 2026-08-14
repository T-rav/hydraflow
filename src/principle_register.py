"""Principle register (#11077) — setpoint-encoded or human-held, nothing between.

The #10824 thesis one level up: **a principle without a setpoint is a finding
generator, not a regulator.** The principles graded "measured but not
enforced" (keep-it-simple, prefer-what-exists, improve-by-rate) are tracked by
real instruments and satisfiable by none of them — there is no value at which
the answer is "this is fine, stop looking", so their output is alarm-fatigue
fodder no matter how good the measurement.

The register (``control/principles.yaml``) forces the classification:

- ``holding: setpoint`` — the principle is encoded with an enforcement that
  can rest (ADR-0044's P1–P10 audit contract is the exemplar: pass = silence).
- ``holding: human`` — explicitly held by a person, with a **currency
  requirement**: ``currency_days`` + ``last_exercised``. A human-held
  principle nobody exercises decays into a stated value; currency staleness
  is surfaced by the principles-audit LOOP at runtime — deliberately NOT a
  CI assertion, which would be a wall-clock time-bomb by design
  (TEST-WALLCLOCK-TIMEBOMB-001).

Nothing stays in the middle: the loader refuses entries with no holding, and
the guard test refuses a register that omits required fields. Pure module —
``now`` is always passed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

import yaml

CONTROL_DIR = "control"
PRINCIPLES_FILENAME = "principles.yaml"


class Holding(StrEnum):
    """The only two allowed states — 'measured but not enforced' is neither."""

    SETPOINT = "setpoint"
    HUMAN = "human"


@dataclass(frozen=True)
class PrincipleEntry:
    principle_id: str
    statement: str
    holding: Holding
    #: setpoint-held: what enforces it (the thing that lets it rest).
    enforced_by: str = ""
    #: human-held: who holds it + the currency contract.
    held_by: str = ""
    currency_days: int = 0
    last_exercised: str = ""  # ISO date, human-updated when exercised
    #: The instruments that MEASURE it (either holding may have these).
    instruments: tuple[str, ...] = ()


def principles_path(repo_root: Path) -> Path:
    return repo_root / CONTROL_DIR / PRINCIPLES_FILENAME


def load_principles(repo_root: Path) -> dict[str, PrincipleEntry]:
    """Load the register. Raises on malformed entries — the register is
    repo-versioned and guard-tested, so failure is a CI bug (fail-closed):
    an unclassifiable principle is exactly the middle state the register
    exists to forbid.
    """
    raw = yaml.safe_load(principles_path(repo_root).read_text()) or {}
    entries: dict[str, PrincipleEntry] = {}
    for pid, raw_entry in raw.items():
        data = raw_entry or {}
        holding = Holding(data["holding"])
        entry = PrincipleEntry(
            principle_id=pid,
            statement=str(data.get("statement", "")),
            holding=holding,
            enforced_by=str(data.get("enforced_by", "")),
            held_by=str(data.get("held_by", "")),
            currency_days=int(data.get("currency_days", 0)),
            last_exercised=str(data.get("last_exercised", "")),
            instruments=tuple(str(i) for i in data.get("instruments", ())),
        )
        if holding is Holding.SETPOINT and not entry.enforced_by:
            msg = f"setpoint-held principle {pid!r} names no enforcement"
            raise ValueError(msg)
        if holding is Holding.HUMAN and (
            not entry.held_by or entry.currency_days <= 0 or not entry.last_exercised
        ):
            msg = (
                f"human-held principle {pid!r} needs held_by + currency_days "
                "+ last_exercised — a currency requirement, or it decays into "
                "a stated value nobody holds"
            )
            raise ValueError(msg)
        entries[pid] = entry
    return entries


@dataclass(frozen=True)
class StaleHolding:
    """A human-held principle past its currency window."""

    principle_id: str
    held_by: str
    days_overdue: int


def stale_holdings(
    entries: dict[str, PrincipleEntry], *, now: datetime
) -> list[StaleHolding]:
    """Human-held principles whose currency has lapsed. Pure; ``now`` is the
    caller's clock (the principles-audit loop passes real time; tests pass a
    fixed instant — never a hardcoded fixture date against real now()).
    """
    stale: list[StaleHolding] = []
    for entry in entries.values():
        if entry.holding is not Holding.HUMAN:
            continue
        exercised = datetime.fromisoformat(entry.last_exercised)
        if exercised.tzinfo is None:
            exercised = exercised.replace(tzinfo=UTC)
        deadline = exercised + timedelta(days=entry.currency_days)
        if now > deadline:
            stale.append(
                StaleHolding(
                    principle_id=entry.principle_id,
                    held_by=entry.held_by,
                    days_overdue=(now - deadline).days,
                )
            )
    return sorted(stale, key=lambda s: s.principle_id)
