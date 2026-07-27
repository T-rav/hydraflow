"""ADR-0023 enforcement: no dead test-local class artifacts.

ADR-0023 (Require Instantiation Verification for Test-Local Classes) decides
(Decision §1) that every ``class`` defined inside a ``def test_*`` /
``async def test_*`` body must be *instantiated or explicitly referenced*
within that same test — the recurring merge/refactor artifact is a helper class
(e.g. ``ExplodingStr``) left behind after the failure-injection it supported
moved to a ``patch`` side effect, surviving ruff/pyright/pytest because Python
happily defines a class nobody constructs.

That invariant is a concretely testable, non-tautological AST property (the ADR
scoped it to *test function bodies only* — module-level helpers are out of
scope, Decision §Scope boundaries), so it earns a REAL asserting check rather
than the review-checklist path. This test walks ``tests/**/test_*.py`` and, for
every class defined directly inside a test function, requires at least one
reference to the class name elsewhere in that function (an ``ast.Name`` load —
an instantiation ``C(...)``, a ``side_effect=C``/``new=C`` argument, a bare
reference — or the name appearing in a string literal, which conservatively
absorbs the ``locals()``/``globals()`` metaprogramming false-positive the ADR
flags). An unreferenced test-local class is the dead artifact ADR-0023 bans.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _enclosing_test_functions(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        and n.name.startswith("test")
    ]


def _class_is_referenced(func: ast.AST, class_node: ast.ClassDef) -> bool:
    """True if *class_node*'s name is used anywhere in *func* other than its own
    definition — a Name load (instantiation / reference) or a string literal
    (metaprogramming escape hatch)."""
    name = class_node.name
    for node in ast.walk(func):
        if node is class_node:
            continue
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and name in node.value
        ):
            return True
    return False


def _dead_test_local_classes(base: Path) -> list[str]:
    """Return ``file::test::ClassName`` for every class defined inside a test
    function body that is never instantiated or referenced within that test."""
    offenders: list[str] = []
    for path in base.rglob("test_*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(base).as_posix()
        for func in _enclosing_test_functions(tree):
            for node in ast.walk(func):
                if isinstance(node, ast.ClassDef) and not _class_is_referenced(
                    func, node
                ):
                    offenders.append(f"{rel}::{func.name}::{node.name}")
    return offenders


def test_no_dead_test_local_classes(real_repo_root: Path) -> None:
    """ADR-0023 §1: every class defined inside a test function body is
    instantiated or referenced within that test — no dead helper-class
    artifacts survive a mock refactor."""
    offenders = _dead_test_local_classes(real_repo_root / "tests")
    assert not offenders, (
        "dead test-local class artifacts found (ADR-0023 requires every class "
        "defined inside a test body to be instantiated or referenced within "
        f"that test): {sorted(offenders)}"
    )
