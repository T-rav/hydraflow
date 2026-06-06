"""Convention guard: factory PR helpers must target the configured base branch.

Root-cause guard for the UL→main PR runaway. Several loops (term-proposer/
-pruner, edge-proposer, entry-evidence via OpenAutoPRBotPRPort, and
pricing-refresh) opened PRs with a hardcoded ``base="main"`` instead of
``config.base_branch()``. Under ADR-0042 (two-tier branch model) those PRs
target ``main`` directly, get BLOCKED by branch protection (main only advances
via ``rc/*`` promotion), and pile up unmerged.

The fix is the established convention everywhere else: pass
``self._config.base_branch()`` (``staging`` when staging is enabled, else
``main``). This AST scan fails if any call to the ``auto_pr`` PR-opening
helpers passes a *literal* ``base="main"`` — a runtime ``base_branch()`` call
is fine, a string constant is the bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

# The auto_pr helpers that branch off / target ``origin/{base}``.
_PR_HELPERS = {"open_automated_pr_async", "open_automated_pr"}


def _called_name(func: ast.expr) -> str | None:
    """Return the simple callee name for ``f(...)`` or ``mod.f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _hardcoded_main_base_calls(tree: ast.Module) -> list[int]:
    """Line numbers of PR-helper calls passing a literal ``base="main"``."""
    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _called_name(node.func) not in _PR_HELPERS:
            continue
        for kw in node.keywords:
            if kw.arg != "base":
                continue
            if isinstance(kw.value, ast.Constant) and kw.value.value == "main":
                violations.append(node.lineno)
    return violations


def test_no_pr_helper_hardcodes_main_base() -> None:
    offenders: dict[str, list[int]] = {}
    for path in SRC_DIR.rglob("*.py"):
        if "/ui/" in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines = _hardcoded_main_base_calls(tree)
        if lines:
            offenders[str(path.relative_to(SRC_DIR))] = lines

    assert not offenders, (
        "Factory PR helpers must target config.base_branch() (staging when "
        'ADR-0042 is enabled), not a hardcoded base="main". Offending calls: '
        f"{offenders}"
    )
