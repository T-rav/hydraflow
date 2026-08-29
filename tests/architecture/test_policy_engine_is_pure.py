"""The decision engine stays a seam, not a layer (#11749, epic #11752).

The delivery principle this gate holds:

    The decision engine never runs pytest, inspects git, launches agents,
    touches worktrees, repairs code, schedules, routes models, manages PRs, or
    owns lifecycle state.

Enumerating those hazards would be the enumeration-drift disease
``docs/standards/parametrised_guards/README.md`` documents — there is always a
sixth way to shell out. So the rule is inverted and fails closed: the engine's
import set is **pinned to a literal, in both directions**. Anything the engine
would need in order to read the world (``pathlib``, ``os``, ``subprocess``,
``socket``, an HTTP client, the repo-reading half of anything) has to appear as
an import first, and adding *any* import — hazardous or not — reddens this file
and forces the question to be asked out loud.

The one hole an import pin leaves is the builtins: ``open()`` needs no import,
and ``__file__`` needs none either. Both are checked separately below.

``policy.facts`` is deliberately NOT covered. Collectors are where the repo
reads belong; that is the whole point of the split.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The modules the pure half of the seam is allowed to reach for, pinned as a
#: literal. Every one of them is data or vocabulary: ``adr_conformance`` and
#: ``adr_conformance_remediation`` contribute enums and one pure classifier
#: (``classify_remediation_over``); ``pydantic`` is the model layer;
#: ``datetime``/``enum``/``typing``/``collections``/``__future__`` are stdlib
#: type machinery. None of them can reach the filesystem, a subprocess, a
#: socket, or the event loop on their own.
_PURE_MODULES: frozenset[str] = frozenset(
    {
        "__future__",
        "adr_conformance",
        "adr_conformance_remediation",
        "collections",
        "datetime",
        "enum",
        "policy",
        "pydantic",
        "typing",
    }
)

#: The two modules that must stay pure. ``policy.store`` and ``policy.facts``
#: are the I/O halves and are excluded on purpose.
_PURE_SOURCES: tuple[str, ...] = (
    "src/policy/models.py",
    "src/policy/python_engine.py",
)


def _tree(rel: str) -> ast.Module:
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _imported_top_level_modules(tree: ast.Module) -> set[str]:
    """Top-level module names imported anywhere in *tree*.

    Includes imports guarded by ``if TYPE_CHECKING`` and any deferred
    function-local import: a read smuggled in behind either would be just as
    much of a world-touch at the moment it ran.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — stays inside the package
                names.add("policy")
            elif node.module:
                names.add(node.module.split(".")[0])
    return names


def test_pure_seam_modules_import_only_pure_modules() -> None:
    """Pinned in BOTH directions: an added import reddens, a removed one too."""
    imported: set[str] = set()
    for rel in _PURE_SOURCES:
        imported |= _imported_top_level_modules(_tree(rel))

    assert imported == set(_PURE_MODULES), (
        "the decision engine's import set drifted from its pin.\n"
        f"  added:   {sorted(imported - _PURE_MODULES)}\n"
        f"  dropped: {sorted(_PURE_MODULES - imported)}\n"
        "If the engine now needs to read something, the read belongs in "
        "policy.facts (a collector), not here — see epic #11752."
    )


def test_pure_seam_modules_never_call_open() -> None:
    """``open()`` is a builtin, so the import pin above cannot see it."""
    offenders = [
        rel
        for rel in _PURE_SOURCES
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
            for node in ast.walk(_tree(rel))
        )
    ]

    assert not offenders, f"{offenders} call open() — collectors do the reading"


def test_pure_seam_modules_never_reference_dunder_file() -> None:
    """``__file__`` is the other import-free route to the filesystem."""
    offenders = [
        rel
        for rel in _PURE_SOURCES
        if any(
            isinstance(node, ast.Name) and node.id == "__file__"
            for node in ast.walk(_tree(rel))
        )
    ]

    assert not offenders, f"{offenders} reference __file__ — the engine has no root"


def test_the_guard_is_looking_at_real_files() -> None:
    """Anti-vacuity: a renamed module must not make this file pass over nothing."""
    for rel in _PURE_SOURCES:
        assert (REPO / rel).is_file(), f"{rel} is missing — the guard sees nothing"
        assert _imported_top_level_modules(_tree(rel)), f"{rel} imports nothing"
