"""Version-controlled baseline (the set-point) for the mass sensor.

Mirrors ``erosion.concentration_baseline``'s ratchet shape: the committed YAML
grandfathers today's god files and god classes with their sizes, and the gate
flags only **new** offenders — a file or class crossing the threshold that the
baseline never recorded. Existing gods grow and shrink as normal work lands;
gating every bump would block routine PRs, but a *new* god class appearing is
a conscious architectural event worth stopping on. Growth of a grandfathered
entry past ``tolerance`` is reported (``grown``) for the loop's roster, never
gated.

YAML shape::

    comment: "<why the baseline last moved>"
    files:
      src/config.py: 7134
    classes:
      src/config.py:HydraFlowConfig: {loc: 4894, methods: 39}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from erosion.models import GodClass, GodFile, MassFinding

#: Relative growth over the baselined LOC before a grandfathered entry is "grown".
DEFAULT_GROWTH_TOLERANCE = 0.10


@dataclass(frozen=True)
class MassBaseline:
    """The grandfathered god files (``{path: loc}``) and god classes (``{key: {loc, methods}}``)."""

    files: dict[str, int] = field(default_factory=dict)
    classes: dict[str, dict[str, int]] = field(default_factory=dict)
    comment: str = ""


@dataclass(frozen=True)
class Growth:
    """One grandfathered entry whose LOC grew past the tolerance since the baseline."""

    key: str
    kind: Literal["file", "class"]
    baseline_loc: int
    loc: int


def load_mass_baseline(path: Path) -> MassBaseline:
    """Load the baseline, or an empty one when the file is absent."""
    if not path.exists():
        return MassBaseline()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    files = {str(k): int(v) for k, v in (raw.get("files", {}) or {}).items()}
    classes = {
        str(k): {"loc": int(v.get("loc", 0)), "methods": int(v.get("methods", 0))}
        for k, v in (raw.get("classes", {}) or {}).items()
    }
    return MassBaseline(
        files=files, classes=classes, comment=str(raw.get("comment", ""))
    )


def save_mass_baseline(path: Path, finding: MassFinding, *, comment: str) -> None:
    """Persist *finding*'s god files/classes as the new baseline (grandfathering them)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "comment": comment,
        "files": {g.path: g.loc for g in finding.god_files},
        "classes": {
            c.key: {"loc": c.loc, "methods": c.methods} for c in finding.god_classes
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def new_god_files(finding: MassFinding, baseline: MassBaseline) -> tuple[GodFile, ...]:
    """God files present now but absent from the baseline — the gate signal."""
    return tuple(g for g in finding.god_files if g.path not in baseline.files)


def new_god_classes(
    finding: MassFinding, baseline: MassBaseline
) -> tuple[GodClass, ...]:
    """God classes present now but absent from the baseline — the gate signal."""
    return tuple(c for c in finding.god_classes if c.key not in baseline.classes)


def grown(
    finding: MassFinding,
    baseline: MassBaseline,
    *,
    tolerance: float = DEFAULT_GROWTH_TOLERANCE,
) -> tuple[Growth, ...]:
    """Grandfathered entries whose LOC grew more than *tolerance* over their baselined size.

    Files first (finding order), then classes. Shrinking is never reported —
    that is decomposition working.
    """
    out: list[Growth] = []
    for g in finding.god_files:
        base = baseline.files.get(g.path)
        if base is not None and g.loc > base * (1 + tolerance):
            out.append(Growth(key=g.path, kind="file", baseline_loc=base, loc=g.loc))
    for c in finding.god_classes:
        entry = baseline.classes.get(c.key)
        if entry is None:
            continue
        base = entry.get("loc", 0)
        if c.loc > base * (1 + tolerance):
            out.append(Growth(key=c.key, kind="class", baseline_loc=base, loc=c.loc))
    return tuple(out)
