"""Every brokered-child runner must hand its spawn seam the id it will claim.

#11990: three runners each generated a ``child_spawn_id``, stamped it onto the
receipt's :class:`driver_contracts.WorkerLineage`, and then spawned without
passing it. ``resolve_harness_env`` fell through to its own ``uuid4`` and the
virtual key was minted under an id that appeared nowhere else — the receipt and
the ledger rows it accounted for could not be joined, and no row named the
driver.

Derived from the tree rather than from a list of the three known runners: the
defect was identical in all three, so the fourth would be written the same way.
A spelled list is a list someone has to remember to extend.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_LINEAGE = "WorkerLineage"
_REQUIRED = ("spawn_id", "driver_id", "parent_spawn_id")


def _functions_building_lineage(tree: ast.AST) -> list[ast.AST]:
    """Every function body that constructs a ``WorkerLineage``."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == _LINEAGE
            ):
                found.append(node)
                break
    return found


def _spawn_calls(func: ast.AST) -> list[ast.Call]:
    """Calls to the injected spawn seam inside *func*."""
    return [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_spawn"
    ]


def _runners_that_spawn_a_child() -> list[tuple[str, ast.AST, ast.Call]]:
    cases = []
    for path in sorted(_SRC.glob("*_worker_runner.py")):
        tree = ast.parse(path.read_text())
        for func in _functions_building_lineage(tree):
            for call in _spawn_calls(func):
                cases.append((path.name, func, call))
    return cases


_CASES = _runners_that_spawn_a_child()


def test_the_sweep_found_the_runners_it_was_built_from() -> None:
    """Anti-vacuity: a predicate that matches nothing would pass every case."""
    names = {name for name, _func, _call in _CASES}

    assert names >= {
        "implement_worker_runner.py",
        "plan_worker_runner.py",
        "review_worker_runner.py",
    }, f"the sweep stopped seeing its own known positives: {names}"


@pytest.mark.parametrize(
    ("module", "func", "call"),
    _CASES,
    ids=[f"{name}::{func.name}" for name, func, _call in _CASES],  # type: ignore[attr-defined]
)
def test_the_spawn_seam_is_told_the_child_id_and_the_driver(
    module: str, func: ast.AST, call: ast.Call
) -> None:
    passed = {kw.arg for kw in call.keywords}

    missing = [name for name in _REQUIRED if name not in passed]
    assert not missing, (
        f"{module}::{func.name} builds a {_LINEAGE} but spawns without "  # type: ignore[attr-defined]
        f"{missing} — the mint will invent its own id and the receipt will "
        f"name a spawn no ledger row shares"
    )
