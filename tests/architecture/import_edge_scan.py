"""One high-fidelity collector for the import edges an arch guard reasons about.

Three import-boundary guards in this repo each re-derived "what is an import"
and each got it wrong in a different way. The bugs were mutation-proven, and
they are the reason this module exists rather than a fourth hand-rolled walk:

* **ADR-0118's OTel ban** matched dotted deny-list entries (``telemetry.spans``)
  against ``ImportFrom.module`` only, never ``alias.name``. ``from telemetry
  import spans`` — the spelling anyone would actually write — walked straight
  past it, while ``import telemetry.spans`` was caught. See
  :data:`EdgeKind.MEMBER`.
* **The ``src`` ↛ ``scripts`` boot guard** (#10365) protects a genuinely
  RUNTIME property — the container ships ``src`` and not ``scripts``, so a
  boot-time ``scripts`` import exits the container — with an import-*name* AST
  scan. ``importlib.import_module("scripts.hydraflow_audit.checks.p1_docs")``
  at module scope reproduces #10365 byte-for-byte and passed.
  ``importlib.util.spec_from_file_location`` is an established idiom in three
  ``src`` modules, so the shape was not hypothetical. See
  :data:`EdgeKind.DYNAMIC`.
* **The decision path's spawn-machinery pin** intersected a deny-list with the
  TOP-LEVEL root of each import. ``from concurrent.futures import
  ProcessPoolExecutor`` reaches the exact machinery ``multiprocessing`` names,
  through a package the collapsed root cannot express. Edges here carry the
  full dotted path.

The shared root cause is the same shape ``docs/standards/parametrised_guards``
is about: a predicate narrower than the vocabulary of the thing it guards, with
nobody to notice, because the guard is green either way. One collector written
once closes all three, and every guard that adopts it inherits the next
fidelity fix for free.

**Pure functions only** — no repo mutation, no subprocesses, no imports of the
modules being scanned. Same contract as ``conformance_offline_scan``,
``subprocess_reap_scan`` and ``quality_only_cli_scan``, which are this module's
fidelity template rather than its competition: they answer *different*
questions (network reach, reap pairing, CLI availability) over the same trees.

Declared limits, stated rather than patched around:

* A module name that is not a string literal — computed at runtime, read from a
  variable, or passed by keyword — is not seen. Same residual class as an argv
  assembled from non-literals.
* ``getattr(importlib, "import_module")("x")`` is dynamic dispatch and a
  lexical scan cannot follow it.
* Boot reachability is *static*: a name imported inside ``if False:`` is
  reported as boot-reachable. That direction is deliberate — the error lands on
  the loud side.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path

__all__ = [
    "EdgeKind",
    "ImportEdge",
    "denied_edges",
    "import_edges",
    "package_of",
    "reaches",
    "resolves_to_module",
]


class EdgeKind(StrEnum):
    """How the edge is spelled in source. All four are real reaches."""

    IMPORT = "import"
    """``import a.b`` — one edge per alias, carrying the full dotted name."""

    FROM = "from"
    """``from a.b import c`` — the edge to ``a.b``, with ``level`` resolved."""

    MEMBER = "from-member"
    """``from a.b import c`` — the edge to ``a.b.c``.

    The edge the OTel guard did not have. ``from telemetry import spans``
    reaches ``telemetry.spans`` whether ``spans`` is a submodule or a name
    re-exported from one, and a deny-list that spells the thing as
    ``telemetry.spans`` means both. :func:`resolves_to_module` answers the
    submodule-vs-symbol question separately, for the failure message, because
    the fix differs even though the verdict does not.
    """

    DYNAMIC = "dynamic"
    """A module named to a call as a string literal.

    ``importlib.import_module("x")``, ``__import__("x")``,
    ``importlib.util.spec_from_file_location("x", "pkg/x.py")``, and every
    wrapper around them.
    """


@dataclass(frozen=True, slots=True)
class ImportEdge:
    """One reach from a file to a module name."""

    module: str
    """Absolute dotted name. Relative imports are resolved; nothing is
    collapsed to its root."""

    kind: EdgeKind
    lineno: int

    boot: bool
    """Reachable when the module is merely imported.

    ``False`` means the edge sits inside a function, a lambda or an
    ``if TYPE_CHECKING:`` body — deferred or elided, and therefore not a
    container-boot concern. A guard whose subject is a runtime boot property
    filters on this; a guard whose subject is "does this file depend on that
    at all" does not.
    """

    statement: str
    """``ast.unparse`` of the statement, for the failure message."""


# ---------------------------------------------------------------------------
# Dynamic imports — resolved from the ARGUMENT, never from the callee
# ---------------------------------------------------------------------------

#: Callees whose first string argument REFERENCES a name rather than importing
#: it. An enumeration, on purpose, and on the SAFE side.
#:
#: The detection rule below is inverted — it reads the ARGUMENT, not the callee
#: — because the callee's identity is unbounded: aliases, star imports,
#: rebinding, ``getattr``, cross-file re-export, and wrappers like
#: ``pytest.importorskip`` or ``mock.patch`` that import as a side effect.
#: ``conformance_offline_scan`` reached the same conclusion after two failed
#: attempts at recognising the callee, and #11717 stopped patching spellings
#: after five. An enumeration on the DETECTION side is a silent false negative;
#: this one is on the safe side, where a callee nobody excluded is a LOUD false
#: positive that whoever writes it hits immediately.
#:
#: Each entry is measured, not guessed. Against ``src/`` today the argument
#: rule produces exactly five candidate hits and all five are these:
#:
#: * ``data.get("scripts", {})`` in ``admin_tasks``, ``prep`` and
#:   ``test_scaffold`` — the ``package.json`` ``scripts`` key, read through the
#:   mapping protocol. ``get`` is the mapping protocol's own spelling; nothing
#:   dynamically imports through it.
#: * ``checkout_path("scripts", "audit_prompts.py")`` in ``prompt_fitness`` and
#:   ``prompt_observatory`` — a repo-relative path builder (#11589), whose
#:   first argument is a DIRECTORY, not a module.
#:
#: ``assert*`` is a prefix rather than a list because every mock and unittest
#: assertion shares it: ``mock_import.assert_called_once_with("boto3")``
#: asserts about an import that was MOCKED and therefore never happened.
#: ``importorskip`` and ``patch`` are deliberately NOT here — both really do
#: import the module they name.
_REFERENCE_CALLEES: Final[frozenset[str]] = frozenset(
    {"checkout_path", "get", "getLogger", "get_logger"}
)


def _callee_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_dotted_name(text: str) -> bool:
    """True when *text* could name a module: dotted, all parts identifiers."""
    parts = text.split(".")
    return bool(parts) and all(part.isidentifier() for part in parts)


def _named_modules(call: ast.Call) -> tuple[str, ...]:
    """Module names *call* hands over as string literals.

    Two shapes, because the two dynamic-import idioms in this repo spell the
    module differently:

    * the FIRST POSITIONAL string literal — ``import_module("pkg.mod")``,
      ``__import__("pkg")``, ``spec_from_file_location("mod", …)``;
    * any string literal ending ``.py``, converted from a path to a dotted
      name — ``spec_from_file_location("mod", "pkg/mod.py")``, where the
      module the loader actually reaches is named by the PATH and the first
      argument is only the name it will be registered under.

    Everything else is inert: the result is only ever intersected with a
    caller's deny-list, so an unrelated string contributes nothing.
    """
    name = _callee_name(call)
    if name.startswith("assert") or name in _REFERENCE_CALLEES:
        return ()
    found: list[str] = []
    first = call.args[0] if call.args else None
    if (
        isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and _is_dotted_name(first.value)
    ):
        found.append(first.value)
    for arg in call.args:
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            continue
        if not arg.value.endswith(".py"):
            continue
        dotted = arg.value.removesuffix(".py").strip("/").replace("/", ".")
        if _is_dotted_name(dotted):
            found.append(dotted)
    return tuple(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Boot reachability
# ---------------------------------------------------------------------------


def _is_type_checking(test: ast.expr) -> bool:
    """``TYPE_CHECKING`` / ``typing.TYPE_CHECKING`` guard conditions."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _children(node: ast.AST, boot: bool) -> Iterator[tuple[ast.AST, bool]]:
    """Every child of *node*, paired with ITS boot reachability.

    Stated as what DEFERS execution, never as a list of the blocks that do not.
    The guard this replaces enumerated the descending shapes — ``If``, ``For``,
    ``While``, ``With``, ``Try``, ``ClassDef`` — and so was blind to
    ``ast.Match``, which arrived in the language after it was written and
    executes at import like every other statement. Anything the grammar adds
    next is handled here by default rather than by someone remembering.

    Three deferrals, and they are the whole rule:

    * a function or lambda BODY runs when it is called, not when the module is
      imported. Decorators and argument defaults DO run at import, so they keep
      the current reachability;
    * an ``if TYPE_CHECKING:`` body is elided at runtime. Its ``orelse`` is
      not, and neither is the test;
    * nothing else. A conditional import inside ``if sys.platform``, a
      ``try/except ImportError`` fallback, a class body, a match arm — all run
      at import, and all are reported as boot-reachable even when the branch
      is never taken. The error lands on the loud side deliberately.
    """
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        for decorator in node.decorator_list:
            yield decorator, boot
        yield node.args, boot
        for stmt in node.body:
            yield stmt, False
        if node.returns is not None:
            yield node.returns, False
        return
    if isinstance(node, ast.Lambda):
        yield node.args, boot
        yield node.body, False
        return
    if isinstance(node, ast.If) and _is_type_checking(node.test):
        yield node.test, boot
        for stmt in node.body:
            yield stmt, False
        for stmt in node.orelse:
            yield stmt, boot
        return
    for child in ast.iter_child_nodes(node):
        yield child, boot


# ---------------------------------------------------------------------------
# Relative-import resolution
# ---------------------------------------------------------------------------


def package_of(path: Path, roots: Sequence[Path]) -> str:
    """Dotted package containing *path*, for resolving relative imports.

    *roots* are the directories a dotted name resolves against, in the order
    ``tests/conftest.py`` puts them on ``sys.path`` — ``src/`` then the repo
    root. ``src/policy/rules.py`` under ``src/`` is package ``policy``.
    """
    for root in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        return ".".join(relative.parts[:-1])
    return ""


def _absolute(node: ast.ImportFrom, package: str) -> str:
    """``from . import x`` resolved against the importing file's package.

    Relative imports are how every ``src`` package re-exports through its
    ``__init__``. A scan that drops ``level > 0`` — which two of the three
    guards this replaces did — stops seeing the whole re-export layer.
    """
    if node.level == 0:
        return node.module or ""
    parts = [part for part in package.split(".") if part]
    climb = node.level - 1
    parts = parts[: len(parts) - climb] if climb <= len(parts) else []
    if node.module:
        parts = [*parts, node.module]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# The collector
# ---------------------------------------------------------------------------

_STATEMENT_LIMIT: Final = 160


def _text(node: ast.AST) -> str:
    try:
        rendered = ast.unparse(node)
    except (AttributeError, ValueError):  # pragma: no cover - defensive
        return "<unparseable>"
    rendered = rendered.replace("\n", " ")
    if len(rendered) > _STATEMENT_LIMIT:
        return rendered[:_STATEMENT_LIMIT] + "…"
    return rendered


def _collect(node: ast.AST, *, boot: bool, package: str, out: list[ImportEdge]) -> None:
    if isinstance(node, ast.Import):
        out.extend(
            ImportEdge(alias.name, EdgeKind.IMPORT, node.lineno, boot, _text(node))
            for alias in node.names
        )
        return
    if isinstance(node, ast.ImportFrom):
        base = _absolute(node, package)
        if base:
            out.append(ImportEdge(base, EdgeKind.FROM, node.lineno, boot, _text(node)))
            out.extend(
                ImportEdge(
                    f"{base}.{alias.name}",
                    EdgeKind.MEMBER,
                    node.lineno,
                    boot,
                    _text(node),
                )
                for alias in node.names
                if alias.name != "*"
            )
        return
    if isinstance(node, ast.Call):
        out.extend(
            ImportEdge(named, EdgeKind.DYNAMIC, node.lineno, boot, _text(node))
            for named in _named_modules(node)
        )
    for child, child_boot in _children(node, boot):
        _collect(child, boot=child_boot, package=package, out=out)


def import_edges(tree: ast.Module, *, package: str = "") -> tuple[ImportEdge, ...]:
    """Every module *tree* reaches, by any of the four spellings."""
    out: list[ImportEdge] = []
    _collect(tree, boot=True, package=package, out=out)
    return tuple(out)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def reaches(module: str, denied: str) -> bool:
    """Does *module* reach *denied* — the module itself or anything under it?

    Dotted-prefix containment on WHOLE components. ``concurrent.futures``
    reaches ``concurrent.futures`` and ``concurrent.futures.process``;
    ``concurrentfoo`` reaches neither, which a bare ``startswith`` would get
    wrong.
    """
    return module == denied or module.startswith(f"{denied}.")


def denied_edges(
    edges: Iterable[ImportEdge], denied: Iterable[str], *, boot_only: bool
) -> tuple[ImportEdge, ...]:
    """The edges in *edges* that reach anything in *denied*.

    *boot_only* narrows to import-time reachability — the filter the container
    boot rule needs and the dependency rules do not.
    """
    wanted = tuple(denied)
    return tuple(
        edge
        for edge in edges
        if (edge.boot or not boot_only)
        and any(reaches(edge.module, entry) for entry in wanted)
    )


def resolves_to_module(dotted: str, roots: Sequence[Path]) -> bool:
    """Does *dotted* name a file on disk under one of *roots*?

    The submodule-vs-symbol question, kept OUT of the verdict on purpose.
    ``from telemetry import spans`` is denied either way — the deny-list names
    ``telemetry.spans`` and that is what the statement reaches. What the answer
    changes is the ADVICE in the failure message: a submodule moves, a
    re-exported name is dropped. Reporting it as a certainty either way would
    be the guard telling the reader something it does not know.
    """
    parts = dotted.split(".")
    if not all(part.isidentifier() for part in parts):
        return False
    for root in roots:
        current = root
        for part in parts[:-1]:
            current = current / part
        last = parts[-1]
        if (current / f"{last}.py").is_file() or (
            current / last / "__init__.py"
        ).is_file():
            return True
    return False
