"""Version-controlled baseline (the Set-point) + ratchet diff for concept-scatter.

Mirrors `disturbance.baseline`'s per-signature Counter + `{comment,
entries}` YAML shape — the DisturbanceDampener baseline-YAML +
diff-bucketing (new/resolved/unchanged) convention epic #10104 calls out
for this sensor's baseline half — rather than `erosion.baseline`'s
single-scalar-norm shape used by the change-spread sensor (#10105): a
`ScatterFinding` is naturally a SET of flagged symbols per change, not one
number, so ratcheting per-symbol (signature = symbol name, count =
distinct modules crossed) is the right fit, same as the disturbance
dampener's own `diff`. Kept local to `erosion` rather than importing
`disturbance` types directly, mirroring `erosion.models`' own
"mirror-the-style, don't cross-import" convention (see that module's
docstring).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from erosion.models import ScatterFinding


@dataclass
class ScatterRatchetResult:
    """Outcome of comparing a `ScatterFinding`'s symbols to a baseline.

    Shape mirrors `disturbance.models.RatchetResult` exactly: `new` /
    `resolved` map symbol -> modules-crossed delta vs. the baseline;
    `unchanged` lists symbols whose scatter degree matches it exactly.
    """

    new: dict[str, int] = field(default_factory=dict)
    resolved: dict[str, int] = field(default_factory=dict)
    unchanged: tuple[str, ...] = ()


def load_scatter_baseline(path: Path) -> dict[str, int]:
    """Load the baselined ``{symbol: modules-crossed}`` map, or ``{}`` when absent."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("entries", {}) or {}
    return {str(k): int(v) for k, v in entries.items()}


def save_scatter_baseline(path: Path, finding: ScatterFinding, *, comment: str) -> None:
    """Persist *finding*'s scattered symbols (symbol -> modules-crossed) as the new norm."""
    entries = {s.symbol: len(s.modules) for s in finding.scattered}
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"comment": comment, "entries": dict(sorted(entries.items()))}
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def diff(finding: ScatterFinding, baseline: dict[str, int]) -> ScatterRatchetResult:
    """Bucket *finding*'s scattered symbols against *baseline* — new/resolved/unchanged.

    Mirrors `disturbance.baseline.diff`: a symbol scattering across MORE
    modules than the baseline records is `new` (module-count excess); fewer
    — including no longer meeting the threshold at all, i.e. absent from
    `finding.scattered` — is `resolved`; an exact match is `unchanged`.
    """
    current = {s.symbol: len(s.modules) for s in finding.scattered}
    signatures = set(current) | set(baseline)
    new: dict[str, int] = {}
    resolved: dict[str, int] = {}
    unchanged: list[str] = []
    for sig in sorted(signatures):
        cur = current.get(sig, 0)
        base = baseline.get(sig, 0)
        if cur > base:
            new[sig] = cur - base
        elif cur < base:
            resolved[sig] = base - cur
        elif cur > 0:
            unchanged.append(sig)
    return ScatterRatchetResult(new=new, resolved=resolved, unchanged=tuple(unchanged))
