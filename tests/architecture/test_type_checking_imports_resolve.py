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

Two halves, because a type-only import can be wrong in two ways. The module can
not exist (the shipped bug), or the module can exist and not carry the symbol —
``from config import CredentialsX``. The second check runs only for modules that
resolve to a file under ``src/``: the symbol table is read with ``ast``, never by
importing, so a module with import-time side effects is never executed.
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


def _from_imports_under_type_checking(
    tree: ast.AST,
) -> list[tuple[int, str, tuple[str, ...]]]:
    """(lineno, module, symbols) for absolute ``from X import a, b`` blocks."""
    found: list[tuple[int, str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.If) and _is_type_checking_test(node.test)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom) and not sub.level and sub.module:
                symbols = tuple(a.name for a in sub.names if a.name != "*")
                if symbols:
                    found.append((sub.lineno, sub.module, symbols))
    return found


def _module_level_names(path: Path) -> set[str]:
    """Names *path* binds at module level, read with ``ast`` — never imported.

    Deliberately permissive: anything bound anywhere in the module's top-level
    body counts, including inside ``if``/``try`` blocks (optional-dependency
    shims, ``TYPE_CHECKING`` re-exports). A false ACCEPT is a missed defect; a
    false REJECT would redden CI on correct code, which is worse.
    """
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def bind(node: ast.AST) -> None:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)

    for node in tree.body:
        bind(node)
        # Conditional top-level bodies (if/try/with) still bind module names.
        if isinstance(node, ast.If | ast.Try | ast.With):
            for sub in ast.walk(node):
                bind(sub)
    return names


def _src_local_source(module: str) -> Path | None:
    """The ``src/``-local file *module* resolves to, or None if it is external."""
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError, AttributeError):
        return None
    if spec is None or not spec.origin:
        return None
    origin = Path(spec.origin)
    try:
        origin.relative_to(_SRC)
    except ValueError:
        return None  # stdlib or third-party — not ours to police
    return origin


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


def test_every_type_checking_import_of_a_src_module_names_a_real_symbol() -> None:
    """The other half: the module resolves, but does it carry the symbol?

    Scoped to modules whose source lives under ``src/`` and read with ``ast``,
    so no module is imported and no import-time side effect runs.
    """
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))

    missing: list[str] = []
    symbol_cache: dict[str, set[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - src must always parse
            continue
        for lineno, module, symbols in _from_imports_under_type_checking(tree):
            if module in _EXEMPT:
                continue
            if module not in symbol_cache:
                source = _src_local_source(module)
                symbol_cache[module] = (
                    _module_level_names(source) if source is not None else set()
                )
                if source is None:
                    continue
            elif not symbol_cache[module]:
                continue
            declared = symbol_cache[module]
            missing.extend(
                f"{path.relative_to(_SRC.parent)}:{lineno} -> "
                f"{module}.{symbol} does not exist"
                for symbol in symbols
                if symbol not in declared
            )

    assert not missing, (
        "TYPE_CHECKING import(s) naming a symbol their module does not define:\n  "
        + "\n  ".join(missing)
        + "\n\nSame blind spot as a wrong module path — the annotation types to "
        "Unknown and pyright, the runtime, and ruff all stay silent "
        "(#11547 review)."
    )
