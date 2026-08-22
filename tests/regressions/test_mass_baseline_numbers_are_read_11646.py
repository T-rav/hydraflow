"""Regression: the numbers in the erosion baselines are read, or they are not there.

#11646 — `disturbance/baselines/mass.yaml` recorded `loc:`/`methods:` that had
rotted for nine classes and eight files, and `ImplementPhase` grew 173 LOC / 5
methods with nothing reporting it. Two distinct defects hid behind one symptom:

1. ``grown()`` only watched the LOC axis, so a class that shrank in lines while
   gaining methods (`AgentRunner`: 1408 → 1388 LOC, 36 → 42 methods) read as
   unchanged on a sensor whose own threshold treats method count as god-making.
2. ``suite_hygiene.yaml`` carried ``total_tests``, which was written, loaded and
   compared by nobody, and drifted +1010 unnoticed.

These pin the mechanism, not the data. The recorded numbers are deliberately not
gated per-PR (measured: 7.4 % of merged commits blocked, remedy = re-record the
number, i.e. the bypass) — they feed the ErosionMetricsLoop's burn-down roster,
so what must not regress is that the committed file's numbers actually reach it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from erosion.mass import collect_sources, compute
from erosion.mass_baseline import (
    MassBaseline,
    grown,
    load_mass_baseline,
)
from erosion_metrics_loop import _render_mass

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MASS = _REPO_ROOT / "disturbance" / "baselines" / "mass.yaml"
_SUITE_HYGIENE = _REPO_ROOT / "disturbance" / "baselines" / "suite_hygiene.yaml"


def test_committed_mass_numbers_reach_the_burn_down_roster() -> None:
    """Halve one committed entry's recorded size; the roster must name it as grown.

    A whole-pipeline pin: committed YAML → ``load_mass_baseline`` → ``grown`` →
    rendered issue body. It fails if any link stops consulting `loc:`/`methods:`.
    """
    live = compute(collect_sources(_REPO_ROOT / "src"))
    committed = load_mass_baseline(_MASS)
    assert committed.classes, "mass.yaml recorded no classes to check"

    victim = next(iter(committed.classes))
    understated = replace(
        committed,
        classes={
            **committed.classes,
            victim: {"loc": 1, "methods": 1},
        },
    )

    growth = grown(live, understated)

    assert victim in {g.key for g in growth}
    _title, body = _render_mass({"finding": live, "growth": growth, "roster": [victim]})
    assert victim in body
    assert "## Grown since baseline" in body


def test_method_only_growth_is_still_growth() -> None:
    """`AgentRunner`'s shape: fewer lines, more methods — silent before #11646."""
    live = compute(collect_sources(_REPO_ROOT / "src"))
    target = next(c for c in live.god_classes if c.methods >= 2)
    generous_loc_but_tight_methods = MassBaseline(
        classes={target.key: {"loc": target.loc * 10, "methods": 1}}
    )

    (growth,) = grown(live, generous_loc_but_tight_methods)

    assert (growth.grew_loc, growth.grew_methods) == (False, True)
    assert growth.methods == target.methods


def test_suite_hygiene_baseline_records_only_marks_the_gate_compares() -> None:
    """Every key in the file is either the comment or a mark ``exceeded()`` reads."""
    raw = yaml.safe_load(_SUITE_HYGIENE.read_text(encoding="utf-8"))

    assert set(raw) == {"comment", "parametrize_copies", "cross_file_duplicates"}
