"""Version-controlled baseline (the set-point) for the concentration sensor.

Mirrors ``erosion.baseline`` / ``disturbance.baseline``'s YAML ``{comment,
entries}`` convention, but — like ``disturbance.baseline`` and unlike the scalar
spread baseline — ``entries`` is a per-module ``{module: fan_in}`` map: the
grandfathered god-files and their tolerated fan-in.

Ratchet direction (the deliberate low-noise choice): the gate flags **NEW**
god-files — a module crossing the threshold that the baseline never recorded —
not every fan-in bump. Existing god-files (``models``, ``config``) gain and shed
importers constantly as normal work; gating that would block routine PRs. But a
*new* concentration point emerging is a conscious architectural event worth
stopping on. Worsening of an existing god-file is reported (``worsened``) for
visibility but is not, by itself, the gate signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from erosion.models import ConcentrationFinding, GodModule


@dataclass(frozen=True)
class ConcentrationBaseline:
    """The baselined god-files and their tolerated fan-in."""

    entries: dict[str, int] = field(default_factory=dict)
    comment: str = ""


def load_concentration_baseline(path: Path) -> ConcentrationBaseline:
    """Load the baselined ``{module: fan_in}`` map, or an empty one when absent."""
    if not path.exists():
        return ConcentrationBaseline()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = {str(k): int(v) for k, v in (raw.get("entries", {}) or {}).items()}
    return ConcentrationBaseline(entries=entries, comment=str(raw.get("comment", "")))


def save_concentration_baseline(
    path: Path, finding: ConcentrationFinding, *, comment: str
) -> None:
    """Persist *finding*'s god-files as the new baseline (grandfathering them)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = {gm.module: gm.fan_in for gm in finding.god_modules}
    payload = {"comment": comment, "entries": entries}
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def new_god_files(
    finding: ConcentrationFinding, baseline: ConcentrationBaseline
) -> tuple[GodModule, ...]:
    """God-files present now but absent from the baseline — the gate signal."""
    return tuple(gm for gm in finding.god_modules if gm.module not in baseline.entries)


def worsened(
    finding: ConcentrationFinding, baseline: ConcentrationBaseline
) -> tuple[GodModule, ...]:
    """Baselined god-files whose fan-in has risen past its recorded value.

    Reported for visibility (a god-file getting worse is worth seeing) but not
    the gate signal — see the module docstring for why.
    """
    return tuple(
        gm
        for gm in finding.god_modules
        if gm.module in baseline.entries and gm.fan_in > baseline.entries[gm.module]
    )
