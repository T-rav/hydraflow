"""Regression: an erosion class-issue title must carry no metric (#11547/#11548).

`ErosionMetricsLoop` refreshes a class issue's BODY every tick
(`update_issue_body`) and has no way to edit its title — `PRPort` has no
`update_issue_title`. `_render_finding` therefore computes a fresh title on each
refresh and DISCARDS it, so any number embedded at filing time is frozen and
silently rots.

Both live issues had already drifted when this was written:

    #11547  title "4898 LOC"                 body 5278 LOC
    #11548  title "784 copies, 19936 tests"  body 401 copies, 23080 tests

A wrong number in the first line a triager reads is worse than no number, and
it is the line that decides whether anyone opens the issue at all.

The guard is "no digit in the title" rather than a title-vs-body comparison: a
comparison needs a body to compare against and would PASS at filing time —
exactly when the two agree and nothing is wrong yet. The property that holds
forever is that the title contains nothing which *can* drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from erosion.models import (
    CrossFileDuplicate,
    GodClass,
    GodFile,
    MassFinding,
    ParametrizeGroup,
    SuiteHygieneFinding,
)
from erosion_metrics_loop import _render_mass, _render_suite_hygiene


def _mass() -> dict[str, object]:
    finding = MassFinding(
        god_files=(GodFile("src/implement_phase.py", 1949),),
        god_classes=(
            GodClass("src/implement_phase.py", "ImplementPhase", 1845, 61),
        ),
        total_files=400,
        file_loc_threshold=1500,
        class_loc_threshold=600,
        class_method_threshold=40,
    )
    return {"kind": "mass", "finding": finding, "growth": (), "roster": []}


def _hygiene() -> dict[str, object]:
    finding = SuiteHygieneFinding(
        total_files=1872,
        total_tests=23080,
        parametrize_groups=(
            ParametrizeGroup("tests/test_a.py", ("test_x", "test_y", "test_z")),
        ),
        cross_file_duplicates=(
            CrossFileDuplicate("test_dup", ("tests/test_a.py", "tests/test_b.py")),
        ),
    )
    return {"kind": "suite_hygiene", "finding": finding, "roster": []}


@pytest.mark.parametrize(
    ("render", "build"), [(_render_mass, _mass), (_render_suite_hygiene, _hygiene)]
)
def test_no_erosion_title_contains_a_digit(render, build) -> None:
    """The invariant, over BOTH renderers.

    Parametrised over the renderer pair rather than asserted once: the mass and
    suite-hygiene titles were written separately and rotted separately, so a
    guard covering only one would have missed the other.
    """
    title, _body = render(build())
    assert not any(ch.isdigit() for ch in title), (
        "a digit in an erosion title will go stale — the loop can edit bodies "
        f"but not titles: {title!r}"
    )


@pytest.mark.parametrize(
    ("render", "build"), [(_render_mass, _mass), (_render_suite_hygiene, _hygiene)]
)
def test_the_metrics_are_still_reported_in_the_body(render, build) -> None:
    """Anti-vacuity: dropping the numbers from the title must not lose them.

    A renderer that emitted no metrics anywhere would satisfy the digit guard
    above while making the issue useless — the guard would then be measuring
    silence rather than correctness.
    """
    _title, body = render(build())
    assert any(ch.isdigit() for ch in body), "the body carries no metrics at all"
    assert "| metric | value |" in body, "the evidence table is missing"
