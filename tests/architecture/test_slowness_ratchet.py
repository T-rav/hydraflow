"""Ratchet for the suite-time sensor (#11910).

**Why this gate is shaped differently from its siblings.** The mass and
suite-hygiene ratchets compare deterministic counts: the same tree yields the
same LOC on any machine, so a rise is unambiguous. Duration is not
deterministic. During this issue's own investigation the same two tests
measured 32s together in isolation and 90s under a loaded host — a 3x swing
with no code change, which also produced two false diagnoses before anyone read
the log.

A gate on raw seconds would fire on contention, be diagnosed as a flake, and be
switched off. This repo has already paid for that failure mode, and the
deletion-scope gate two issues ago paid for the mirror image of it (a gate that
could not see its subject and went green).

So:

* the gate is on **share** — the fraction of measured runtime the slow tests
  hold. Contention inflates every duration together, so a ratio survives it;
* ``tolerance`` absorbs the residual non-uniform part;
* per-test seconds are recorded for the roster and **never gated**;
* an **unmeasured** run is skipped, not passed. No measurement is not evidence
  of a fast suite, and a gate that treats it as one is the silent-green shape
  this repo keeps finding.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from erosion.slowness import collect_durations, compute
from erosion.slowness_baseline import (
    SlownessBaseline,
    exceeded,
    load_slowness_baseline,
)

_ROOT = Path(__file__).resolve().parents[2]
_BASELINE = _ROOT / "disturbance/baselines/slowness.yaml"
_DURATIONS = _ROOT / ".hydraflow/test_durations.json"


def _reading(slow_seconds: float, fast_total: float, *, scale: float = 1.0):
    """A measurement holding ONE slow test and enough fast ones to make up the rest.

    The fast side must be spread across many sub-threshold tests: a single
    "rest": 75.0 entry is itself over the 10s threshold and would count as slow,
    making every share 100%. That mistake is why these fixtures are built rather
    than written out.
    """
    fast_each = 0.5 * scale
    n = max(int(round(fast_total * scale / fast_each)), 1)
    return compute(
        {"slow": slow_seconds * scale, **{f"fast{i}": fast_each for i in range(n)}},
        threshold_seconds=10.0,
    )


class TestTheGateItself:
    """Exercised on synthetic readings, so it is proven without a slow suite."""

    def test_a_share_within_tolerance_passes(self) -> None:
        base = SlownessBaseline(max_slow_share=0.20, tolerance=0.10)
        # 25% held by the slow test: 5 points over the mark, inside tolerance.
        finding = _reading(slow_seconds=25.0, fast_total=75.0)
        assert round(finding.share, 2) == 0.25
        assert exceeded(finding, base) == ()

    def test_a_share_past_the_tolerance_is_reported(self) -> None:
        base = SlownessBaseline(max_slow_share=0.20, tolerance=0.10)
        finding = _reading(slow_seconds=60.0, fast_total=40.0)
        assert exceeded(finding, base), "a 60% share must breach a 20%+10% mark"

    def test_uniform_contention_does_not_trip_it(self) -> None:
        """The property the whole design rests on: doubling every duration
        leaves the ratio — and therefore the verdict — unchanged."""
        base = SlownessBaseline(max_slow_share=0.30, tolerance=0.10)
        quiet = _reading(slow_seconds=25.0, fast_total=75.0)
        loaded = _reading(slow_seconds=25.0, fast_total=75.0, scale=2.0)
        assert quiet.share == loaded.share
        assert exceeded(quiet, base) == exceeded(loaded, base) == ()

    def test_an_unmeasured_reading_is_skipped_not_passed(self) -> None:
        """Absence of measurement is not evidence of a fast suite."""
        base = SlownessBaseline(max_slow_share=0.01, tolerance=0.0)
        assert exceeded(compute({}), base) == ()

    def test_an_unrecorded_baseline_cannot_be_regressed_against(self) -> None:
        assert exceeded(_reading(99.0, 1.0), SlownessBaseline()) == ()


class TestTheCommittedBaseline:
    def test_the_baseline_is_recorded_and_well_formed(self) -> None:
        """Anti-vacuity: an empty mark makes every assertion above serene."""
        base = load_slowness_baseline(_BASELINE)
        assert not base.is_empty, (
            f"{_BASELINE} has no max_slow_share — run "
            "`make test && python scripts/regen_slowness_baseline.py --reason ...`"
        )
        assert 0.0 <= base.max_slow_share <= 1.0
        assert base.slow_tests, "a mark with no named tests cannot report growth"

    def test_every_baselined_test_still_exists(self) -> None:
        """#11673's lesson, applied here: a mark keyed on a node that no longer
        resolves reads as progress to a shrink-only gate."""
        base = load_slowness_baseline(_BASELINE)
        dead = [
            nodeid
            for nodeid in base.slow_tests
            if not (_ROOT / nodeid.split("::", 1)[0]).is_file()
        ]
        assert not dead, (
            f"slowness baseline names tests whose file is gone: {dead}. "
            "Re-point or re-record; a vanished entry silently shrinks the mark."
        )


@pytest.mark.skipif(
    not _DURATIONS.exists(), reason="no measurement — run `make test` to produce one"
)
def test_the_live_reading_is_within_the_mark() -> None:
    """The gate proper. Skipped rather than failed when nothing measured it —
    CI lanes that do not run the full suite must not be told the suite regressed.
    """
    finding = compute(collect_durations(_DURATIONS))
    breaches = exceeded(finding, load_slowness_baseline(_BASELINE))
    assert not breaches, "\n".join(breaches) + (
        "\n\nProfile before optimising: every offender found under this issue "
        "was one accidentally-quadratic call, not accumulated work. If the "
        "suite genuinely got faster, re-record with "
        "scripts/regen_slowness_baseline.py."
    )
