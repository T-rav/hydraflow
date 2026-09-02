#!/usr/bin/env python3
"""Answer the one question Layer 3 owes: which factory is degrading, since when?

#11690 fixes the scope deliberately narrowly — *across N factories, which is
degrading, and since when?* Everything else a telemetry stack usually grows is
absent on purpose, because the volume that justifies it does not exist here
(868 bytes x 6/day x 100 factories x 1 year is about 200 MB).

**Degrading means a shrink-only counter went up.** HydraFlow's baselines are
ratchets: ``suppressions``, ``concentration``, ``suite_hygiene`` and the rest
are all "this may only shrink". So a rise is not a trend to interpret, it is a
ratchet moving the wrong way, and the reading where it first rose is the "since
when".

**Compared within one identity, never across hosts.** Two factories reporting
different numbers are usually two different repos or two different SHAs, and
subtracting those is meaningless. A regression is a rise against that same
repo+host's own previous reading, which is why the sink partitions by identity.

Stdlib only. DuckDB is the ad-hoc query path for an operator with the tree
mounted (see README); this is the same question answered as code, so it can be
tested without a database and run anywhere the tree can be read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Reading:
    """One emitted document, reduced to what the question needs."""

    repo: str
    host: str
    emitted_at: str
    head_sha: str
    metrics: dict[str, float]

    @property
    def identity(self) -> tuple[str, str]:
        return (self.repo, self.host)


@dataclass(frozen=True, slots=True)
class Regression:
    """One shrink-only metric that rose, and the reading where it first rose."""

    repo: str
    host: str
    metric: str
    was: float
    now: float
    since: str
    """``emitted_at`` of the EARLIEST reading at or above ``now``.

    Not the latest reading's timestamp. An operator asking "since when" wants
    when it broke, and reporting the newest reading would answer "just now"
    every time no matter how long it had been broken.
    """

    @property
    def delta(self) -> float:
        return self.now - self.was


def flatten(document: dict[str, Any]) -> dict[str, float]:
    """``baselines.suppressions."entries.count"`` -> ``suppressions.entries.count``.

    Flat keys because the comparison is per metric and a nested walk at every
    comparison would be the same traversal written twice.
    """
    flat: dict[str, float] = {}
    for baseline, metrics in (document.get("baselines") or {}).items():
        for name, value in (metrics or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                flat[f"{baseline}.{name}"] = float(value)
    return flat


def read_tree(root: Path) -> tuple[Reading, ...]:
    """Every readable document under *root*, oldest first.

    A malformed file is SKIPPED rather than fatal: this reads a directory an
    operator syncs from object storage, where a partial upload is ordinary. One
    truncated file must not make every other factory unqueryable — the failure
    mode a fail-fast reader would have here is "one bad host hides the rest".
    """
    readings = []
    for path in sorted(root.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        identity = document.get("identity") or {}
        emitted = document.get("emitted_at")
        if not isinstance(document, dict) or not emitted:
            continue
        readings.append(
            Reading(
                repo=str(identity.get("repo") or ""),
                host=str(identity.get("host") or ""),
                emitted_at=str(emitted),
                head_sha=str(identity.get("head_sha") or ""),
                metrics=flatten(document),
            )
        )
    return tuple(sorted(readings, key=lambda r: r.emitted_at))


def regressions(readings: tuple[Reading, ...]) -> tuple[Regression, ...]:
    """Every shrink-only metric now above where that identity started."""
    by_identity: dict[tuple[str, str], list[Reading]] = {}
    for reading in readings:
        by_identity.setdefault(reading.identity, []).append(reading)

    found: list[Regression] = []
    for (repo, host), series in sorted(by_identity.items()):
        # A single reading needs no special case: `first` and `latest` are then
        # the same object, so `now <= was` holds for every metric and nothing is
        # reported. An explicit `len(series) < 2` guard was here and was dead —
        # removing it changed no test, which is the definition of a claim that
        # was not true. The property it described is real and still asserted by
        # `test_one_reading_is_never_degrading`; it just holds structurally.
        first, latest = series[0], series[-1]
        for metric, now in sorted(latest.metrics.items()):
            was = first.metrics.get(metric)
            if was is None or now <= was:
                continue
            since = next(
                (r.emitted_at for r in series if r.metrics.get(metric, was) >= now),
                latest.emitted_at,
            )
            found.append(
                Regression(
                    repo=repo, host=host, metric=metric, was=was, now=now, since=since
                )
            )
    return tuple(found)


def report(root: Path) -> str:
    """A human line per regression, worst delta first, or an explicit all-clear."""
    found = regressions(read_tree(root))
    if not found:
        return "no factory is degrading"
    lines = ["degrading:"]
    lines.extend(
        f"  {r.repo} {r.host}  {r.metric}  {r.was:g} -> {r.now:g} "
        f"(+{r.delta:g}) since {r.since}"
        for r in sorted(found, key=lambda r: -r.delta)
    )
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - operator entry point
    import sys

    print(report(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))
