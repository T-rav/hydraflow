"""Version-controlled baseline (the Set-point) for the change-spread sensor.

Mirrors `disturbance.baseline`'s YAML convention — same `{comment, entries}`
shape, same human-readable `comment` field, same load-defaults-when-missing
/ save-overwrites API shape (`load_baseline`/`save_baseline` there,
`load_spread_baseline`/`save_spread_baseline` here). The metric differs:
`disturbance.baseline.diff` ratchets a `{signature: count}` map built from a
repo-wide `detect()` sweep; a change-spread reading is a single scalar per
change (`SpreadFinding.spread_ratio`), not a per-signature count, so there's
nothing to ratchet per-signature — instead `entries` holds one scalar norm
under a fixed key, and `is_flagged` compares a single finding against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from erosion.models import SpreadFinding

_RATIO_KEY = "max_spread_ratio"

#: Fallback norm when no baseline file has been saved yet: at most one
#: module crossed per file touched (no file "shares" its module concept
#: with another touched file, but no MORE spread than that is tolerated).
DEFAULT_MAX_SPREAD_RATIO = 1.0


@dataclass(frozen=True)
class SpreadBaseline:
    """The baselined norm: modules crossed tolerated per file touched."""

    max_spread_ratio: float
    comment: str = ""


def load_spread_baseline(
    path: Path, *, default: float = DEFAULT_MAX_SPREAD_RATIO
) -> SpreadBaseline:
    """Load the baselined max spread ratio, or *default* when absent."""
    if not path.exists():
        return SpreadBaseline(max_spread_ratio=default)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("entries", {}) or {}
    ratio = entries.get(_RATIO_KEY, default)
    return SpreadBaseline(
        max_spread_ratio=float(ratio), comment=str(raw.get("comment", ""))
    )


def save_spread_baseline(path: Path, ratio: float, *, comment: str) -> None:
    """Persist *ratio* as the new baselined norm, human-readable `comment` alongside."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"comment": comment, "entries": {_RATIO_KEY: ratio}}
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def is_flagged(finding: SpreadFinding, baseline: SpreadBaseline) -> bool:
    """True when *finding*'s spread ratio exceeds the baselined norm.

    Mirrors the ratchet's "new" direction (`disturbance.baseline.diff`):
    only a rise past the baseline flags; equal-or-below is silent, so a
    change matching the historical norm exactly is not shotgun surgery.
    """
    return finding.spread_ratio > baseline.max_spread_ratio
