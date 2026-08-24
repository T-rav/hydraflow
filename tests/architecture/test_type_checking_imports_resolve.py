"""Every import inside an ``if TYPE_CHECKING:`` block under ``src/`` must resolve.

Nothing else catches a typo there. ``pyproject.toml`` sets
``reportMissingImports = false``, so pyright is silent; ``from __future__ import
annotations`` makes the annotation a never-evaluated string, so the runtime is
silent; and ruff's ``F401`` stays quiet because an annotation *does* reference
the name. The import is simply never resolved by anything.

#11696 shipped four copies of ``from credentials import Credentials`` — there is
no top-level ``credentials`` module; the class is ``config.Credentials``. Every
annotation in those four files typed to ``Unknown`` and no tool said a word
(#11547 review). This is that word.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

#: Modules legitimately absent from the test environment (optional extras whose
#: types are still annotated). Add with a reason; empty is the healthy state.
_EXEMPT: frozenset[str] = frozenset()


def _is_type_checking_test(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _absolute_imports_under_type_checking(tree: ast.AST) -> list[tuple[int, str]]:
    """(lineno, module) for every absolute import inside a TYPE_CHECKING block."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.If) and _is_type_checking_test(node.test)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom):
                # Relative imports resolve against the package, not sys.path.
                if not sub.level and sub.module:
                    found.append((sub.lineno, sub.module))
            elif isinstance(sub, ast.Import):
                found.extend((sub.lineno, alias.name) for alias in sub.names)
    return found


def _resolves(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def test_every_type_checking_import_under_src_resolves() -> None:
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))

    unresolved: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - src must always parse
            continue
        for lineno, module in _absolute_imports_under_type_checking(tree):
            if module in _EXEMPT or _resolves(module):
                continue
            unresolved.append(f"{path.relative_to(_SRC.parent)}:{lineno} -> {module!r}")

    assert not unresolved, (
        "TYPE_CHECKING import(s) that do not resolve:\n  "
        + "\n  ".join(unresolved)
        + "\n\nThe annotation typed to Unknown and nothing complained: pyright is "
        "muted by reportMissingImports=false, the runtime never evaluates the "
        "string annotation, and ruff's F401 sees the name referenced. Fix the "
        "module path, or add it to _EXEMPT with a reason if it is an optional "
        "extra absent from the test environment (#11547 review)."
    )
