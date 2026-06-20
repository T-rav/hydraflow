"""Regression guard for issue #9508: bound all background-loop ``communicate()``.

Issue #9486 traced a 14h ``TrustFleetSanityLoop`` stall to an unbounded
``await proc.communicate()`` on a wedged ``gh issue list``. #9508 found this is
a *systemic class*, not a one-off: 10+ caretaker loops await
``proc.communicate()`` with no timeout, and there is no per-cycle watchdog at
the supervisor layer (``orchestrator.py`` only restarts loops that COMPLETE or
RAISE — a coroutine hung on an ``await`` stays PENDING forever).

A subprocess whose pipe never drains makes ``proc.communicate()`` block
indefinitely. Inside a background loop's ``_do_work`` that means the cycle never
returns, ``_execute_cycle`` never completes, and the orchestrator never sees the
task finish or raise, so it is never restarted — a silent, indefinite stall.

The fix is the convention already used elsewhere in the same files
(``await asyncio.wait_for(proc.communicate(), timeout=...)`` — see e.g.
``staging_bisect_loop.py`` and ``trust_fleet_sanity_loop.py``): every
``communicate()`` in a background loop must be *bounded* by a timeout, whether
via ``asyncio.wait_for`` or an enclosing ``async with asyncio.timeout(...)``
block (or a shared bounded-subprocess helper that wraps one of those).

This AST scan fails if any background-loop file (``src/*_loop.py``) *directly
awaits* ``something.communicate()`` outside a timeout context. A bare
``await proc.communicate()`` is the bug; a ``wait_for``/``timeout``-wrapped one
is fine.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"

# Context-manager callables that bound an enclosed ``await`` (asyncio.timeout /
# asyncio.timeout_at, or their bare-imported forms).
_TIMEOUT_CMS = {"timeout", "timeout_at"}


def _callee_name(func: ast.expr) -> str | None:
    """Return the simple callee name for ``f(...)`` or ``mod.f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_timeout_cm(item: ast.withitem) -> bool:
    """True if a ``with`` item is an ``asyncio.timeout(...)``-style bound."""
    expr = item.context_expr
    return isinstance(expr, ast.Call) and _callee_name(expr.func) in _TIMEOUT_CMS


class _UnboundedCommunicateFinder(ast.NodeVisitor):
    """Collect line numbers of directly-awaited, unbounded ``communicate()``.

    Tracks enclosing ``async with asyncio.timeout(...)`` depth so that a
    ``communicate()`` awaited inside such a block is treated as bounded.
    ``asyncio.wait_for(proc.communicate(), ...)`` is bounded by construction:
    the awaited expression is the ``wait_for`` call, not ``communicate`` itself,
    so it never trips the ``visit_Await`` check below.
    """

    def __init__(self) -> None:
        self.violations: list[int] = []
        self._timeout_depth = 0

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        bounded = any(_is_timeout_cm(item) for item in node.items)
        if bounded:
            self._timeout_depth += 1
        self.generic_visit(node)
        if bounded:
            self._timeout_depth -= 1

    def visit_Await(self, node: ast.Await) -> None:
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "communicate"
            and self._timeout_depth == 0
        ):
            self.violations.append(node.lineno)
        self.generic_visit(node)


def _unbounded_communicate_lines(tree: ast.Module) -> list[int]:
    finder = _UnboundedCommunicateFinder()
    finder.visit(tree)
    return finder.violations


def test_no_background_loop_awaits_unbounded_communicate() -> None:
    offenders: dict[str, list[int]] = {}
    for path in sorted(SRC_DIR.rglob("*_loop.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines = _unbounded_communicate_lines(tree)
        if lines:
            offenders[str(path.relative_to(SRC_DIR))] = lines

    assert not offenders, (
        "Background loops must bound every subprocess communicate() with a "
        "timeout (asyncio.wait_for or `async with asyncio.timeout(...)`), or a "
        "shared bounded-subprocess helper. An unbounded `await "
        "proc.communicate()` on a wedged child silently stalls the loop "
        "forever (issue #9508; root cause of the 14h stall in #9486). "
        f"Unbounded call sites: {offenders}"
    )
