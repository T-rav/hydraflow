"""Version-controlled baseline (the Set-point) + ratchet diff."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from disturbance.models import Finding, RatchetResult


def load_baseline(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("entries", {}) or {}
    return {str(k): int(v) for k, v in entries.items()}


def save_baseline(path: Path, findings: list[Finding], *, comment: str) -> None:
    counts = Counter(f.signature for f in findings)
    entries = {sig: counts[sig] for sig in sorted(counts)}
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"comment": comment, "entries": entries}
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def diff(current: list[Finding], baseline: dict[str, int]) -> RatchetResult:
    counts = Counter(f.signature for f in current)
    signatures = set(counts) | set(baseline)
    new: dict[str, int] = {}
    resolved: dict[str, int] = {}
    unchanged: list[str] = []
    for sig in sorted(signatures):
        cur = counts.get(sig, 0)
        base = baseline.get(sig, 0)
        if cur > base:
            new[sig] = cur - base
        elif cur < base:
            resolved[sig] = base - cur
        elif cur > 0:
            unchanged.append(sig)
    return RatchetResult(new=new, resolved=resolved, unchanged=tuple(unchanged))
