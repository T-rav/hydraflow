"""Regression pin for issue #10402: `_GIT_TIMEOUT_S` scatter across modules.

The concept-scatter sensor (#10106) flagged a single merged change that
independently introduced ``_GIT_TIMEOUT_S = 60`` in three modules; a
follow-up triage found the same byte-identical constant duplicated across
seven read-only git adapters:

- ``audit.detect``
- ``escape.detect``
- ``escape_ledger_loop``
- ``erosion.scatter``
- ``erosion.spread``
- ``erosion_metrics_loop``
- ``arch.generators.traceability_matrix``

#10402 consolidated all seven into one shared leaf constant,
``git_timeouts.GIT_READONLY_TIMEOUT_S``. This pin fails if a future change
reintroduces a local ``_GIT_TIMEOUT_S`` module constant in any of the seven
call sites (the scatter coming back), or if it collapses one of the two
*deliberately distinct* git timeout tiers (fast-fail status endpoint, heavy
audit git call) into the shared constant — those stay separate per
``git_timeouts``'s own docstring and ``tests/regressions/test_issue_9555.py``.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import git_timeouts

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"

# The seven modules #10402 consolidated onto git_timeouts.GIT_READONLY_TIMEOUT_S.
_CONSOLIDATED_MODULES = [
    "audit.detect",
    "escape.detect",
    "escape_ledger_loop",
    "erosion.scatter",
    "erosion.spread",
    "erosion_metrics_loop",
    "arch.generators.traceability_matrix",
]


def _module_level_assigned_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_shared_constant_value_unchanged() -> None:
    """The consolidated value must preserve the pre-#10402 behaviour."""
    assert git_timeouts.GIT_READONLY_TIMEOUT_S == 60


def test_no_src_module_redefines_git_timeout_s() -> None:
    """Runtime AST scan of the full ``src/`` tree — not just the seven
    originally-scattered files — for a reintroduced ``_GIT_TIMEOUT_S``
    module-level constant. A hardcoded file list would miss the scatter
    reappearing in a module that didn't exist at #10402 fix time."""
    offenders: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if "_GIT_TIMEOUT_S" in _module_level_assigned_names(tree):
            offenders.append(str(path.relative_to(SRC_DIR)))

    assert not offenders, (
        "a local `_GIT_TIMEOUT_S` module constant reappeared — #10402 "
        "consolidated this onto git_timeouts.GIT_READONLY_TIMEOUT_S; do not "
        f"reintroduce a local module constant. Offending modules: {offenders}"
    )


def test_all_consolidated_modules_import_shared_constant() -> None:
    """Each call site must actually reference the shared constant, not just
    happen to lack a local shadow."""
    for module_name in _CONSOLIDATED_MODULES:
        module = importlib.import_module(module_name)
        src = inspect.getsource(module)
        assert "GIT_READONLY_TIMEOUT_S" in src, (
            f"{module_name} no longer references "
            f"git_timeouts.GIT_READONLY_TIMEOUT_S — #10402's consolidation "
            f"was reverted without restoring a local timeout bound"
        )


def test_deliberately_distinct_tiers_are_not_collapsed() -> None:
    """The fast-fail and audit git tiers stay separate, separate-valued
    constants — they must NOT be unified with the read-only adapter tier."""
    import git_revision
    import principles_audit_loop

    assert git_revision._GIT_TIMEOUT_SECS == 5
    assert principles_audit_loop._GIT_TIMEOUT_SECONDS == 120
    assert git_timeouts.GIT_READONLY_TIMEOUT_S == 60

    values = {
        git_revision._GIT_TIMEOUT_SECS,
        principles_audit_loop._GIT_TIMEOUT_SECONDS,
        git_timeouts.GIT_READONLY_TIMEOUT_S,
    }
    assert len(values) == 3, (
        "the three git timeout tiers collapsed onto shared values — "
        "fast-fail (5s), read-only adapters (60s), and audit (120s) are "
        "deliberately distinct bounds for different call patterns"
    )
