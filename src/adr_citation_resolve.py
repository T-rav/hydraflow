"""Deterministic ADR citation resolver (#10540, #10533).

Violation-based replacement for the activity-based ADR-drift heuristic
(``adr_drift.compute_drift`` → ``AdrTouchpointAuditorLoop`` →
``AdrDriftResolverLoop``). Instead of the probabilistic "a cited module
changed in a PR" signal (~70% false positives), this answers a concrete,
deterministic question: does every symbol-qualified ``src/...py:Symbol``
citation in an ADR still resolve against the current source tree?

A citation is *unresolved* (a violation) when:

* its file is missing from the repo, OR
* it carries a ``:Symbol`` tail that no longer resolves in that file.

Resolution walks the module AST (``ast.parse``), never importing the target
module — so the resolver is pure, side-effect-free, and safe to run in the
normal "Tests" CI lane as a gate. See
``tests/test_adr_citation_conformance.py``.

Symbol grammar (mirrors ``adr_index._SOURCE_FILE_CITATION_RE``):

* **Bare name** — ``Bar`` — resolves if a top-level ``ClassDef`` /
  ``FunctionDef`` / ``AsyncFunctionDef`` OR a module-level assignment target
  (``Bar = ...`` / ``Bar: T = ...``) is named ``Bar``.
* **Dotted name** — ``Outer.inner`` (or deeper) — resolves if each
  non-final component names a def/class you can descend into, and the final
  component names a def/class OR an assigned name directly within that scope.
  So ``Bar.baz`` resolves when ``baz`` is a method/nested def/class/attribute
  directly under class/def ``Bar``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from adr_index import ADR, ADRIndex


# Glob / placeholder metacharacters. A citation path containing any of these
# is an *illustrative pattern* (``src/*_loop.py``, ``src/**/*.py``,
# ``src/<domain>/*.py``) an ADR uses in prose to mean "a family of files", not
# a concrete file to resolve. Such paths never named a single file the old
# ``compute_drift`` gate could match either, so they are exempt here too.
_GLOB_CHARS = frozenset("*?<>[]")


def _is_concrete_path(path: str) -> bool:
    """True iff *path* is a concrete file path, not a glob/placeholder pattern."""
    return not (_GLOB_CHARS & set(path))


def _assign_target_names(target: ast.expr) -> set[str]:
    """Names bound by one assignment target, unpacking tuple/list targets."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return _assign_target_names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        names: set[str] = set()
        for elt in target.elts:
            names |= _assign_target_names(elt)
        return names
    return set()


def _scope(body: list[ast.stmt]) -> tuple[dict[str, list[ast.stmt]], set[str]]:
    """Split a statement body into (descendable defs/classes, assigned names).

    ``defs`` maps each directly-nested ``ClassDef``/``FunctionDef``/
    ``AsyncFunctionDef`` name to its own body (so a dotted citation can descend
    one level per component). ``assigns`` is the set of names bound by
    directly-nested ``Assign``/``AnnAssign`` targets — module-level constants
    for a bare citation, class attributes for a dotted final component.
    """
    defs: dict[str, list[ast.stmt]] = {}
    assigns: set[str] = set()
    for node in body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            defs[node.name] = node.body
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                assigns |= _assign_target_names(tgt)
        elif isinstance(node, ast.AnnAssign):
            assigns |= _assign_target_names(node.target)
    return defs, assigns


def _symbol_resolves(tree: ast.Module, symbol: str) -> bool:
    """True iff dotted *symbol* resolves by walking *tree*'s nested scopes.

    Each non-final component must name a def/class to descend into; the final
    component resolves as a def/class or an assigned name at that scope.
    """
    parts = symbol.split(".")
    body: list[ast.stmt] = tree.body
    for i, part in enumerate(parts):
        defs, assigns = _scope(body)
        is_last = i == len(parts) - 1
        if part in defs:
            if is_last:
                return True
            body = defs[part]
            continue
        return bool(is_last and part in assigns)
    return False


def _parse_module(file_path: Path) -> ast.Module | None:
    """Parse *file_path* to an AST, or ``None`` if missing/unparseable."""
    try:
        source = file_path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _unresolved_for_adr(
    adr: ADR, repo_root: Path, _cache: dict[str, ast.Module | None]
) -> list[tuple[int, str, str]]:
    """Unresolved ``(number, path, symbol)`` citations for a single ADR."""
    out: list[tuple[int, str, str]] = []
    for path in sorted(adr.source_symbols):
        if not _is_concrete_path(path):
            continue
        symbols = adr.source_symbols[path]
        if not symbols:
            # Bare ``src/foo.py`` citation with no ``:Symbol`` tail: a
            # file-level *dependency pointer*, not a decision anchor. Exempt
            # from existence checks — a removal ADR legitimately references a
            # deleted file (e.g. ADR-0065 "Remove CodeGroomingLoop" cites the
            # very file it removed), and a Proposed ADR forward-references a
            # planned file that does not exist yet (e.g. ADR-0087's
            # ``src/prompt_template.py``). Only symbol-qualified citations are
            # enforced. Mirrors the bare-vs-symbol split in ``adr_drift.py``.
            continue
        if path not in _cache:
            _cache[path] = _parse_module(repo_root / path)
        tree = _cache[path]
        if tree is None:
            # Symbol-qualified citation to a missing/unparseable file: a dead
            # anchor — you cannot cite a symbol in a file that is not there.
            out.extend((adr.number, path, sym) for sym in sorted(symbols))
            continue
        for sym in sorted(symbols):
            if not _symbol_resolves(tree, sym):
                out.append((adr.number, path, sym))
    return out


def _unresolved(adrs: Iterable[ADR], repo_root: Path) -> list[tuple[int, str, str]]:
    cache: dict[str, ast.Module | None] = {}
    out: list[tuple[int, str, str]] = []
    for adr in adrs:
        out.extend(_unresolved_for_adr(adr, repo_root, cache))
    return sorted(out)


def unresolved_citations(
    adr_index: ADRIndex, *, repo_root: Path | None = None
) -> list[tuple[int, str, str]]:
    """Every ADR citation that no longer resolves against the source tree.

    Returns a sorted list of ``(adr_number, path, symbol)`` — one entry per
    violation, where *symbol* is ``""`` for a bare citation to a missing file.
    A citation is a violation when its file is missing, or when its ``:Symbol``
    tail does not resolve in that file (see module docstring for the grammar).

    Scoped to **live** (Accepted / Proposed) ADRs — the same status filter the
    existing P2 gate uses (``ADRIndex.adrs_touching``). Superseded/Deprecated
    ADRs are frozen history: their citations may legitimately point at code
    that has since been removed, so holding them to the current source tree
    would be wrong. Glob/placeholder citation paths are skipped (see
    :func:`_is_concrete_path`).

    *repo_root* defaults to the ADR directory's grandparent (``docs/adr`` →
    repo root); pass it explicitly in tmp_path unit tests.
    """
    if repo_root is None:
        repo_root = Path(adr_index.adr_dir).parent.parent
    live = [a for a in adr_index.adrs() if a.status in ("Accepted", "Proposed")]
    return _unresolved(live, repo_root)
