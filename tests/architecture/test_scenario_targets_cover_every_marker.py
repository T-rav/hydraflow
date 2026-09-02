"""`make scenario-all` must select exactly what the per-marker targets do.

CI's `Scenario Tests` job runs one combined invocation instead of the two the
Makefile also offers, because two processes pay two interpreter starts, two
collections of the whole tree and two xdist pools. That is only safe while the
combined marker expression is the *union* of the individual ones.

The failure this prevents is silent, which is why it is a test and not a
comment: adding a `scenario_foo` marker and a `scenario-foo:` target gives you a
green local run and a green CI run, while CI never executes a single one of
those tests. Nothing goes red — the suite simply stops being covered, which is
the same shape as #11853 (a correct function nobody called) and #11845's job
that measured a browser it no longer downloaded.

So the expression is not compared against a list written here. Both sides are
read out of the Makefile.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"

#: A scenario target's recipe: `pytest tests/scenarios/ -m <expr>`.
_MARKER = re.compile(r"pytest tests/scenarios/ -m (\"[^\"]+\"|\S+)")


def _markers_by_target() -> dict[str, str]:
    """Every `scenario*` target mapped to the marker expression it selects."""
    found: dict[str, str] = {}
    target: str | None = None
    for line in _MAKEFILE.read_text(encoding="utf-8").splitlines():
        name = re.match(r"^(scenario[a-z-]*):", line)
        if name:
            target = name.group(1)
            continue
        if target and not line.startswith(("\t", " ")) and line.strip():
            target = None
            continue
        if target:
            hit = _MARKER.search(line)
            if hit:
                found[target] = hit.group(1).strip('"')
                target = None
    return found


def _atoms(expression: str) -> frozenset[str]:
    """The marker names in an expression, ignoring the `or`/`and` between them."""
    return frozenset(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)) - {
        "or",
        "and",
        "not",
    }


def test_the_makefile_scan_found_the_targets_it_reasons_about() -> None:
    """Anti-vacuity floor: every assertion below is trivially true on {}."""
    found = _markers_by_target()

    assert {"scenario", "scenario-loops", "scenario-all"} <= set(found), found


def test_the_combined_target_selects_every_per_marker_target_s_markers() -> None:
    """The union property CI's single invocation depends on."""
    found = _markers_by_target()
    combined = _atoms(found["scenario-all"])
    individual = {
        marker
        for target, expression in found.items()
        if target != "scenario-all"
        for marker in _atoms(expression)
    }

    assert individual <= combined, (
        f"`make scenario-all` selects {sorted(combined)} but the per-marker "
        f"targets between them select {sorted(individual)}. CI runs only "
        f"scenario-all, so {sorted(individual - combined)} would never execute "
        f"there while every local run and every job stayed green."
    )


def test_the_combined_target_selects_nothing_extra() -> None:
    """The other direction: a marker no target owns is a typo, not coverage."""
    found = _markers_by_target()
    combined = _atoms(found["scenario-all"])
    individual = {
        marker
        for target, expression in found.items()
        if target != "scenario-all"
        for marker in _atoms(expression)
    }

    assert combined <= individual, (
        f"`make scenario-all` names {sorted(combined - individual)}, which no "
        f"per-marker target selects — most likely a misspelling that quietly "
        f"selects nothing"
    )


@pytest.mark.parametrize("target", ["scenario", "scenario-loops", "scenario-all"])
def test_every_scenario_target_runs_in_parallel(target: str) -> None:
    """The speedup is the point; a target that lost the flag is a regression."""
    text = _MAKEFILE.read_text(encoding="utf-8")
    recipe = text.split(f"\n{target}:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]

    assert "$(SCENARIO_PARALLEL)" in recipe, target
