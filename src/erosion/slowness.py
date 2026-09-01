"""Pure suite-time sensor — which tests hold the clock, and how concentrated.

The fourth whole-tree reading, next to ``erosion.mass`` (god files and god
classes by size) and ``erosion.suite_hygiene`` (structural test redundancy).
Those two ask what the suite *is*; this one asks what it *costs*.

**Why it exists.** ``tests/conftest.py`` already fails any test whose call phase
passes a 60s budget, which is a gate: it stops the worst case and says nothing
about the trend. Two tests reached 90s under parallel load and blew the 300s
timeout on two separate branches before anyone looked, and when they were
finally profiled neither was slow in the "does a lot of work" sense — each had
one accidentally-quadratic call worth 4-5x (#11910). A gate cannot surface that
because a test at 55s is invisible to it right up until it is not.

**The purity contract is the same as ``erosion.mass.compute``**: ``compute``
takes an explicit ``{nodeid: seconds}`` mapping and never touches the
filesystem, a clock, or pytest. That is the one real departure this sensor
makes from its siblings — mass and suite-hygiene derive their reading by
PARSING source, and duration cannot be derived from text at all. So the
measurement has to be handed in, and ``collect_durations`` is the thin adapter
that reads the artifact ``conftest`` writes when ``HYDRAFLOW_DURATIONS_OUT``
is set.

That distinction matters for how the reading is used: a mass reading is true of
the tree, while a slowness reading is only ever true of the RUN that produced
it. A contended host inflates every number, so a reading taken on a busy
machine says nothing about the suite — which is why the roster reports
``share`` (a ratio, stable under uniform slowdown) alongside the raw seconds.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from erosion.models import SlownessFinding, SlowTest

#: Call-phase seconds at or above which a test is worth naming on the roster.
#: Deliberately well under ``conftest._SLOW_TEST_BUDGET_S`` (the 60s GATE): the
#: roster's job is to show a test climbing toward the budget, not to re-report
#: the ones that already crossed it.
DEFAULT_SLOW_TEST_SECONDS = 10.0


def compute(
    durations: Mapping[str, float],
    *,
    threshold_seconds: float = DEFAULT_SLOW_TEST_SECONDS,
) -> SlownessFinding:
    """The suite-time reading over an explicit ``{nodeid: seconds}`` mapping.

    Pure: no I/O, no clock, no pytest. Ordering is slowest-first and ties break
    on nodeid, so the roster is stable across runs that measure the same set.
    """
    slow = tuple(
        SlowTest(nodeid=nodeid, seconds=seconds)
        for nodeid, seconds in sorted(durations.items(), key=lambda kv: (-kv[1], kv[0]))
        if seconds >= threshold_seconds
    )
    return SlownessFinding(
        slow_tests=slow,
        total_seconds=sum(durations.values()),
        total_tests=len(durations),
        threshold_seconds=threshold_seconds,
    )


def collect_durations(path: Path) -> dict[str, float]:
    """Read the ``{nodeid: seconds}`` artifact ``conftest`` writes.

    The filesystem adapter, kept out of :func:`compute` so the sensor stays
    unit-testable on synthetic input. A missing or unreadable artifact yields
    ``{}`` — no measurement is not the same as a fast suite, and every caller
    is expected to treat an empty reading as "not measured" rather than "clean"
    (``SlownessFinding.is_empty`` is true for both, so callers check
    ``total_tests`` when the difference matters).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(nodeid): float(seconds)
        for nodeid, seconds in raw.items()
        if isinstance(seconds, int | float)
    }
