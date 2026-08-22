"""Version-controlled baseline (the set-point) for the mass sensor.

Mirrors ``erosion.concentration_baseline``'s ratchet shape: the committed YAML
grandfathers today's god files and god classes with their sizes, and the gate
flags only **new** offenders — a file or class crossing the threshold that the
baseline never recorded. Existing gods grow and shrink as normal work lands;
gating every bump would block routine PRs, but a *new* god class appearing is
a conscious architectural event worth stopping on. Growth of a grandfathered
entry past ``tolerance`` is reported (``grown``) for the loop's roster, never
gated — the measured cost of gating it is 7.4 % of merged PRs blocked, whose
only in-scope remedy would be re-recording the number, i.e. the bypass (#11646).

The recorded ``loc``/``methods`` are therefore **read**, not decoration:
``grown`` compares them against the live reading on both god-making axes and
``ErosionMetricsLoop`` renders the result in the burn-down roster. Both axes
matter — ``AgentRunner`` shrank 1408 → 1388 LOC while gaining six methods, and
a LOC-only reading scored that as "not grown".

Keeping them honest is what ``refresh_entries`` is for: it rewrites exactly the
named entries and leaves every other one byte-identical, so a decomposition PR
can record the two entries it shrank without laundering every other class's
unrelated growth through its diff.

YAML shape::

    comment: "<why the baseline last moved>"
    files:
      src/config.py: 7134
    classes:
      src/config.py:HydraFlowConfig: {loc: 4894, methods: 39}
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeVar

import yaml

from erosion.models import GodClass, GodFile, MassFinding

#: One recorded value: a file's LOC, or a class's ``{loc, methods}``.
_Entry = TypeVar("_Entry", int, dict[str, int])

#: Relative growth over the baselined LOC / method count before a grandfathered
#: entry is "grown".
DEFAULT_GROWTH_TOLERANCE = 0.10


@dataclass(frozen=True)
class MassBaseline:
    """The grandfathered god files (``{path: loc}``) and god classes (``{key: {loc, methods}}``)."""

    files: dict[str, int] = field(default_factory=dict)
    classes: dict[str, dict[str, int]] = field(default_factory=dict)
    comment: str = ""


@dataclass(frozen=True)
class Growth:
    """One grandfathered entry that grew past the tolerance on either god-making axis.

    ``grew_loc``/``grew_methods`` say which axis tripped, so the roster can name
    it. File entries have no method axis (``baseline_methods == methods == 0``).
    """

    key: str
    kind: Literal["file", "class"]
    baseline_loc: int
    loc: int
    baseline_methods: int = 0
    methods: int = 0
    grew_loc: bool = True
    grew_methods: bool = False


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


def write_mass_baseline(path: Path, baseline: MassBaseline) -> None:
    """Serialize *baseline* — the single writer, so untouched entries stay byte-stable.

    ``refresh_entries`` relies on this: load → mutate the named keys → write,
    with every other line reproduced exactly as it was.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "comment": baseline.comment,
        "files": dict(baseline.files),
        "classes": {
            key: {"loc": entry["loc"], "methods": entry["methods"]}
            for key, entry in baseline.classes.items()
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def save_mass_baseline(path: Path, finding: MassFinding, *, comment: str) -> None:
    """Persist *finding*'s god files/classes as the new baseline (grandfathering them)."""
    write_mass_baseline(path, baseline_from(finding, comment=comment))


def baseline_from(finding: MassFinding, *, comment: str = "") -> MassBaseline:
    """The baseline that would grandfather every entry in *finding*."""
    return MassBaseline(
        files={g.path: g.loc for g in finding.god_files},
        classes={
            c.key: {"loc": c.loc, "methods": c.methods} for c in finding.god_classes
        },
        comment=comment,
    )


def _reconcile(
    recorded: dict[str, _Entry],
    current: Mapping[str, _Entry],
    key: str,
    *,
    label: str,
) -> Literal["updated", "removed", "unchanged"]:
    """Point *recorded[key]* at reality; report which of the three things happened."""
    if key not in recorded and key not in current:
        raise KeyError(
            f"{key!r} is not in the baseline and is not a god {label} in the "
            "live reading — check the spelling (class keys look like "
            "'src/foo.py:Bar', file keys like 'src/foo.py')"
        )
    if key not in current:
        recorded.pop(key, None)
        return "removed"
    if recorded.get(key) != current[key]:
        recorded[key] = current[key]
        return "updated"
    return "unchanged"


def refresh_entries(
    baseline: MassBaseline,
    finding: MassFinding,
    keys: Iterable[str],
    /,
) -> tuple[MassBaseline, tuple[str, ...], tuple[str, ...]]:
    """Re-record exactly *keys* against the live *finding*; leave the rest alone.

    A key is a file path (``src/foo.py``) or a class key (``src/foo.py:Bar``).
    An entry still over threshold is updated in place; one that has fallen below
    it — decomposition working — is removed, so the membership gate will catch it
    if it ever crosses again. A key that is live but **not yet baselined is
    adopted**: that is how a genuinely new god class is grandfathered after the
    ratchet trips on it. Returns ``(baseline, updated, removed)`` where *updated*
    names only the entries whose recorded numbers actually changed.

    Raises ``KeyError`` for a key that is neither baselined nor live: a typo must
    never pass silently as a no-op refresh. A key repeated in *keys* is applied
    once — otherwise the second pass over a just-removed entry would find it in
    neither table and accuse a correctly-spelled key of being a typo, discarding
    the other keys' refreshes with it.
    """
    live = baseline_from(finding)
    keys = list(dict.fromkeys(keys))
    files = dict(baseline.files)
    classes = dict(baseline.classes)
    updated: list[str] = []
    removed: list[str] = []

    for key in keys:
        if ":" in key:
            action = _reconcile(classes, live.classes, key, label="class")
        else:
            action = _reconcile(files, live.files, key, label="file")
        if action == "updated":
            updated.append(key)
        elif action == "removed":
            removed.append(key)

    return (
        MassBaseline(files=files, classes=classes, comment=baseline.comment),
        tuple(updated),
        tuple(removed),
    )


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
    """Grandfathered entries that grew more than *tolerance* over their baselined size.

    Both god-making axes count for classes: a class is a god class when EITHER
    its LOC or its method count crosses the threshold, so either axis growing is
    growth. ``AgentRunner`` is the worked case — it shrank 1408 → 1388 LOC while
    gaining six methods (36 → 42), which a LOC-only reading scored as unchanged.

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
        base_loc = entry.get("loc", 0)
        base_methods = entry.get("methods", 0)
        grew_loc = c.loc > base_loc * (1 + tolerance)
        grew_methods = c.methods > base_methods * (1 + tolerance)
        if grew_loc or grew_methods:
            out.append(
                Growth(
                    key=c.key,
                    kind="class",
                    baseline_loc=base_loc,
                    loc=c.loc,
                    baseline_methods=base_methods,
                    methods=c.methods,
                    grew_loc=grew_loc,
                    grew_methods=grew_methods,
                )
            )
    return tuple(out)
