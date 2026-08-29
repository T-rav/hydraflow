"""The decision engine stays a seam, not a layer (#11749, epic #11752).

The delivery principle this gate holds:

    The decision engine never runs pytest, inspects git, launches agents,
    touches worktrees, repairs code, schedules, routes models, manages PRs, or
    owns lifecycle state.

Enumerating those hazards would be the enumeration-drift disease
``docs/standards/parametrised_guards/README.md`` documents — there is always a
sixth way to shell out. So every rule below is **inverted**: nothing is denied
by name, everything is pinned by allow-list in both directions, and the pins
are **per source file** rather than pooled, so one module cannot inherit
another's permissions. An unlisted construct reddens (loud, and cheap to
resolve) instead of passing (silent, and expensive to discover).

Four allow-lists, because there are four ways a name reaches this code:

1. **Imports** — :data:`_PURE_IMPORTS`, keyed by source, then by *dotted*
   module, then pinned down to the individual symbols. Module granularity is
   not enough: a module name says nothing about which half of it was taken,
   and both of this seam's neighbours are mixed. ``adr_conformance`` carries
   two enums *and* ``live_debt``/``accepted_adrs``/``parse_exemptions``, which
   scan the repo; ``policy.facts`` carries two vocabulary constants *and* the
   collectors. Symbols are pinned by their **source** name, never the alias,
   so ``import live_debt as CheckOutcome`` cannot land on a pinned pair.
2. **Builtins** — :data:`_PURE_BUILTINS`. No import is needed to reach
   ``open``, ``__import__``, ``exec``, ``eval``, ``compile``, ``__file__`` or
   ``__builtins__``, so the import pin is blind to all of them. Rather than
   list those seven (and miss the eighth), the guard computes every name the
   module uses *without binding it* and pins that set whole.
3. **Shadowing** — a binding that shadows one of those names would make it
   look bound, and rule 2 would stop seeing it. Refusing all shadowing closes
   that. See the note on ``del`` in :func:`_bound_names`: unbinding is not
   binding, and treating it as one reopened this exact hole once already.
4. **String annotations** — a quoted annotation is an ``ast.Constant``, so
   rules 1 and 2 never look inside it, while pydantic resolves it with
   ``eval`` against module globals at class-creation time. Both pure sources
   carry ``from __future__ import annotations``, so a quoted annotation has no
   legitimate use here and is refused outright rather than parsed.

**What a false red costs, and how to resolve one.** Inversion moves the error
to the loud side, and this file is where you will meet it: adding a genuinely
pure import, calling a builtin the seam has not used before, or naming a local
``id`` all fail this file rather than failing review. Note that rule 3's
forbidden set includes ``id``, ``type``, ``hash``, ``format``, ``next``,
``object``, ``set`` and ``filter`` — so a *pydantic field* named ``id`` or
``type`` reddens too, and there the fix is a schema decision, not a local
rename. That is the intended trade: the cost is one deliberate edit here, and
the question it forces is "can the thing I just added reach the world?".

Resolve a red by answering that question, then widening the *specific* pin for
the *specific* source: add the one symbol to that file's entry in
:data:`_PURE_IMPORTS`, or the one builtin to its entry in
:data:`_PURE_BUILTINS`. Do not widen a pin back out to module granularity, do
not pool the two files' pins, do not re-add a whole module because you needed
one enum from it, and do not delete a rule because it is in the way. If the
new name *can* reach the world, the read belongs in ``policy.facts`` as a
collector — that split is the whole point of epic #11752, and this file
failing is that split working.

**Scope, honestly stated.** This is a static drift gate over two files, not a
sandbox and not a runtime assertion.

*It cannot see* what an allowed object resolves to at runtime: a caller who
walks ``__mro__`` off a pinned class reaches anything, and no parser stops
that. *It also does not constrain the transitive import graph* — importing
``policy.python_engine`` executes ``policy.facts`` and ``adr_conformance``,
and module-scope I/O added there would not redden here. Both are deliberate
limits, and ``tests/architecture/egress_guard.py`` (an ``sys.addaudithook``
lane that observes real ``open``/``connect``/``Popen`` calls) is the
instrument that closes them; wiring the engine into it is tracked separately.

What this file *does* stop is the realistic failure: someone — human or agent
— reaching for the convenient import or the convenient builtin, in good faith,
and nobody noticing.
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Marks ``import x`` (as opposed to ``from x import name``) in the import
#: inventory. A bare import binds the whole module object and hands the seam
#: every attribute it has, which is precisely the granularity this pin exists
#: to refuse — so the sentinel is never blessed. Convert such an import to
#: ``from x import <the name you actually wanted>`` and pin that.
_WHOLE_MODULE = "<module>"

#: Every symbol each pure source may import, keyed by source, then by dotted
#: module. Per source on purpose: ``python_engine`` has no business importing
#: ``pydantic`` or ``datetime`` just because ``models`` legitimately does.
#:
#: ``adr_conformance`` gives two enums; its repo-scanning half (``live_debt``,
#: ``live_grandfathered``, ``parse_exemptions``, ``accepted_adrs``) is left
#: out on purpose. ``adr_conformance_remediation`` gives an enum and one pure
#: classifier. ``policy.facts`` gives the two standard-id constants — the
#: shared vocabulary the ledger is keyed by — and none of its collectors.
#: ``policy.store`` (the ledger writer) appears nowhere and must not.
_PURE_IMPORTS: dict[str, dict[str, frozenset[str]]] = {
    "src/policy/models.py": {
        "__future__": frozenset({"annotations"}),
        "adr_conformance_remediation": frozenset({"RemediationAction"}),
        "collections.abc": frozenset({"Sequence"}),
        "datetime": frozenset({"datetime"}),
        "enum": frozenset({"StrEnum"}),
        "pydantic": frozenset({"BaseModel", "Field", "computed_field"}),
        "typing": frozenset({"TYPE_CHECKING", "Protocol", "runtime_checkable"}),
    },
    "src/policy/python_engine.py": {
        "__future__": frozenset({"annotations"}),
        "adr_conformance": frozenset({"CheckOutcome", "EnforcementClass"}),
        "adr_conformance_remediation": frozenset(
            {"RemediationAction", "classify_remediation_over"}
        ),
        "collections.abc": frozenset({"Sequence"}),
        "policy.facts": frozenset(
            {"STANDARD_ADR_CONFORMANCE", "STANDARD_ADR_ENFORCEMENT"}
        ),
        "policy.models": frozenset(
            {"Charter", "DecisionStatus", "Fact", "FactValue", "StandardDecision"}
        ),
        "typing": frozenset({"TYPE_CHECKING"}),
    },
}

#: Every builtin each pure source may reach for. All of them are type
#: constructors, container types, or decorators; none takes an argument that
#: names a file, a module, or a command. ``open``, ``__import__``, ``exec``,
#: ``eval``, ``compile``, ``__file__`` and ``__builtins__`` are absent for
#: that reason — the engine has no root and must not learn one.
_PURE_BUILTINS: dict[str, frozenset[str]] = {
    "src/policy/models.py": frozenset(
        {"bool", "classmethod", "float", "int", "list", "property", "str"}
    ),
    "src/policy/python_engine.py": frozenset(
        {
            "Exception",
            "bool",
            "dict",
            "frozenset",
            "int",
            "list",
            "sorted",
            "staticmethod",
            "str",
            "tuple",
        }
    ),
}

#: Every name each pure source may use *in an annotation*, pinned per source.
#:
#: Pydantic resolves annotations with ``eval`` at class-creation time, so an
#: annotation is executable code that rules 1 and 2 cannot read. Refusing the
#: shapes that smuggle a string into one is the losing half of this game — a
#: draft that denied ``_A = "..."`` by AST shape was walked past by
#: ``(_A := "...")``, ``_A = "in" + "t"``, ``_B = _A``, tuple-unpacking, a for
#: target and ``x: N.A``, each a spelling of the same idea. So the rule is
#: inverted like the other three: an annotation may only *name* something on
#: this list, and every smuggled binding reddens because no smuggler's name is
#: on it.
_PURE_ANNOTATIONS: dict[str, frozenset[str]] = {
    "src/policy/models.py": frozenset(
        {
            "Charter",
            "CharterArticles",
            "DecisionStatus",
            "Fact",
            "FactValue",
            "RemediationAction",
            "Sequence",
            "StandardDecision",
            "bool",
            "datetime",
            "list",
            "str",
        }
    ),
    "src/policy/python_engine.py": frozenset(
        {
            "Charter",
            "Fact",
            "FactValue",
            "Sequence",
            "StandardDecision",
            "dict",
            "frozenset",
            "list",
            "str",
            "tuple",
        }
    ),
}

#: The modules that must stay pure — the *subjects* of this file, derived from
#: the pins so the three lists cannot drift apart.
_PURE_SOURCES: tuple[str, ...] = tuple(_PURE_IMPORTS)

#: The other half of the package: the modules that are *allowed* to touch the
#: world, listed so that :func:`test_every_policy_module_is_classified` can
#: prove the two lists together account for every file in ``src/policy/``.
#: ``__init__`` is the package facade and re-exports from ``store``, so it is
#: an I/O module too.
_IO_SOURCES: tuple[str, ...] = (
    "src/policy/__init__.py",
    "src/policy/facts.py",
    "src/policy/store.py",
)

#: The package whose every module must fall in one list or the other.
_POLICY_PACKAGE = "src/policy"

#: Where :data:`_PURE_SOURCES` are rooted, so a relative import can be
#: resolved to the dotted module it actually names.
_SOURCE_ROOT = "src"

#: Names the import system injects into a module that are NOT in
#: ``dir(builtins)`` — ``builtins`` is compiled in, so it has no ``__file__``
#: and no ``__builtins__`` of its own. Rule 3 needs them explicitly or it
#: leaves a hole exactly where rule 2 is most load-bearing:
#: ``__cached__`` is the ``.pyc`` path, three ``parents`` from the repo root.
#:
#: This is a hand-written list, which is the shape that rots. It is kept
#: honest from the safe side by
#: :func:`test_forbidden_bindings_covers_every_module_dunder`, which derives
#: the real set from live imported modules and fails if this literal has
#: fallen behind — that is how ``__cached__`` and ``__annotations__`` were
#: found missing after the first draft claimed the list was closed.
_MODULE_DUNDERS: frozenset[str] = frozenset(
    {
        "__annotations__",
        "__builtins__",
        "__cached__",
        "__dict__",
        "__doc__",
        "__file__",
        "__loader__",
        "__name__",
        "__package__",
        "__path__",
        "__spec__",
    }
)


def _forbidden_bindings() -> frozenset[str]:
    """Names no pure source may bind, because binding one blinds rule 2."""
    return frozenset(dir(builtins)) | _MODULE_DUNDERS


def _tree(rel: str) -> ast.Module:
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _package_of(rel: str) -> list[str]:
    """The dotted package containing *rel*, as parts.

    ``src/policy/python_engine.py`` lives in package ``policy``, so a
    ``from . import x`` inside it names ``policy.x``.
    """
    parts = Path(rel).parts
    if parts[0] != _SOURCE_ROOT:
        raise AssertionError(
            f"{rel} is not under {_SOURCE_ROOT}/ — relative imports inside it "
            "cannot be resolved, so this guard would silently mis-attribute "
            "them. Fix _SOURCE_ROOT rather than dropping the source."
        )
    return list(parts[1:-1])


def _imported_symbols(rel: str, tree: ast.Module) -> set[tuple[str, str]]:
    """``(dotted module, source symbol)`` for every import anywhere in *tree*.

    Includes imports guarded by ``if TYPE_CHECKING`` and any deferred
    function-local import: a read smuggled in behind either would be just as
    much of a world-touch at the moment it ran. Relative imports are resolved
    against the source's own package, so ``from .store import x`` is pinned as
    ``policy.store`` and cannot hide behind the package name.

    The symbol recorded is ``alias.name``, never ``alias.asname``. Recording
    the alias would let ``from adr_conformance import live_debt as
    CheckOutcome`` land on an already-pinned pair and walk straight through.
    """
    package = _package_of(rel)
    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update((alias.name, _WHOLE_MODULE) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package):
                    raise AssertionError(
                        f"{rel}: `from {'.' * node.level}{node.module or ''} "
                        "import ...` reaches above the top-level package. "
                        "CPython raises ImportError for this, and resolving it "
                        "here would invent a module name that might collide "
                        "with a pinned one."
                    )
                base = package[: len(package) - (node.level - 1)]
                parts = [*base, node.module] if node.module else base
            else:
                parts = [node.module] if node.module else []
            module = ".".join(parts)
            found.update((module, alias.name) for alias in node.names)
    return found


def _bindings(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Every ``(name, binding construct)`` this module binds — THE oracle.

    Both rules that ask "what does this module bind?" read this one function.
    They used to enumerate binding forms separately, and the narrower of the
    two missed ``match``/``case`` captures: a pinned type could be rebound to a
    string where the free-name rule could see the binding and the rebind rule
    could not. Two tables over one vocabulary is how that happens, so there is
    now one table.

    Deliberately scope-blind, and deliberately counts ``global`` — a function
    called at import can rebind a module global, and a parameter shadowing a
    pinned name hides it from every rule below.

    ``ast.Del`` is NOT a binding: ``del x`` unbinds. Counting it would let
    ``ROOT = __file__`` followed by ``del __file__`` cancel the ``Load`` that
    rule 2 keys on — a demonstrated escape. A genuinely local name is still
    bound by its ``Store``, so ignoring ``Del`` cannot cause a false red.

    Capture patterns (``case x:``, ``case ... as x:``, ``case [*rest]:``,
    ``case {**rest}:``) carry their name as a plain string attribute rather
    than an ``ast.Name``, which is exactly why a hand-rolled ``Store`` sweep
    misses them. PEP 695 (``type X = ...``, ``def f[T]``) has the same shape;
    unreachable while pyproject pins <3.12, and it belongs here when that lifts.
    """
    found: list[tuple[str, ast.AST]] = []
    assigned: set[int] = set()

    # First pass: attribute a plain assignment target to its *statement*, so
    # the rebind rule can inspect the value that was bound to it.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assigned.add(id(target))
                    found.append((target.id, node))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.extend(
                ((alias.asname or alias.name).split(".")[0], node)
                for alias in node.names
            )
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if id(node) not in assigned:
                found.append((node.id, node))
        elif isinstance(node, ast.arg):
            found.append((node.arg, node))
        elif isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler),
        ):
            # A def/class name is always present; ExceptHandler.name is None
            # for `except E:` with no `as` clause, which binds nothing.
            if node.name:
                found.append((node.name, node))
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
            if node.name:
                found.append((node.name, node))
        elif isinstance(node, ast.MatchMapping):
            if node.rest:
                found.append((node.rest, node))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            found.extend((name, node) for name in node.names)
    return found


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name *tree* binds, from the one oracle."""
    return {name for name, _node in _bindings(tree)}


def _free_names(tree: ast.Module) -> set[str]:
    """Names *tree* reads without ever binding them — i.e. the builtins it uses.

    This is the rule the import pin cannot express: ``open()``,
    ``__import__("subprocess")``, ``__builtins__["open"]`` and ``__file__``
    all arrive with no import statement to inspect.
    """
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return loaded - _bound_names(tree)


def _shadowed_builtins(tree: ast.Module) -> list[str]:
    """Names *tree* binds that would blind rule 2 for that name."""
    return sorted(_bound_names(tree) & _forbidden_bindings())


def _annotation_nodes(tree: ast.Module) -> list[ast.expr]:
    """Every expression used as an annotation anywhere in *tree*."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.AnnAssign, ast.arg)) and node.annotation:
            found.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
            found.append(node.returns)
    return found


def _string_annotations(tree: ast.Module) -> list[str]:
    """String constants appearing anywhere inside an annotation.

    Pydantic resolves these with ``eval`` against module globals and builtins,
    so a quoted annotation is executable code that rules 1 and 2 cannot read.
    Both pure sources use ``from __future__ import annotations``, so quoting
    is never necessary; ``typing.Literal["a"]`` would be the one legitimate
    source of a string here, and adding ``Literal`` reddens the import pin
    first — which is the conversation this is meant to force.
    """
    return [
        node.value
        for annotation in _annotation_nodes(tree)
        for node in ast.walk(annotation)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _annotation_names(tree: ast.Module) -> set[str]:
    """Every name referenced from an annotation."""
    return {
        node.id
        for annotation in _annotation_nodes(tree)
        for node in ast.walk(annotation)
        if isinstance(node, ast.Name)
    }


#: The AST node types a *type expression* may be built from: names,
#: subscripts, unions and tuples — nothing that computes, and **no dots**.
#:
#: ``ast.Attribute`` is deliberately absent. Only the base of a dotted name is
#: vetted, so ``Fact = DecisionStatus.SUPERSEDED`` reaches an author-controlled
#: string off an allowed base — the same reach
#: :func:`test_pure_seam_modules_have_no_dotted_annotations` already refuses
#: one hop away, in the annotation itself. Neither pure source binds a pinned
#: name to a dotted value, so refusing it outright costs nothing.
_TYPE_EXPRESSION_NODES: tuple[type[ast.AST], ...] = (
    ast.Name,
    ast.Subscript,
    ast.Tuple,
    ast.List,
    ast.BinOp,
    ast.BitOr,
    ast.Load,
)


def _is_type_expression(node: ast.expr, vetted: frozenset[str]) -> bool:
    """Is *node* a type alias built only from *vetted* names?

    Two conditions, and the second is the one that took three passes to get
    right. The grammar check alone (names, subscripts, unions) is
    satisfied by ``datetime = _X`` — a single ``Name`` — while ``_X`` holds a
    string one line above. Checking the shape of the alias without checking
    what it is made of just moves the smuggling one hop up the chain.

    So every name inside the alias must itself be something this file has
    already vetted: a pinned annotation type, or a pinned builtin for the same
    source. ``_X`` is neither, so the chain reddens at its first link.

    ``None`` and ``...`` are legal inside a type expression; a **string** is a
    forward reference, which is precisely what pydantic hands to ``eval``.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Constant):
            if isinstance(child.value, str):
                return False
            continue
        if isinstance(child, ast.Name):
            if child.id not in vetted:
                return False
            continue
        if not isinstance(child, _TYPE_EXPRESSION_NODES):
            return False
    return True


#: Binding constructs that cannot smuggle a value into a name: importing a
#: type, or defining one with ``class``/``def``.
_SAFE_BINDING_NODES: tuple[type[ast.AST], ...] = (
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)


def _rebound_annotation_names(rel: str, tree: ast.Module) -> list[str]:
    """Pinned annotation names bound to something that is not a type.

    Pinning *which names* an annotation may reference is only half the rule: a
    name already on the pin can be rebound to a string, and the annotation
    referencing it still reads as compliant. ``datetime = "<expr>"`` above the
    model bodies executes at import while every other rule stays green.

    So the value side is inverted too, and — this is the part that took four
    passes — it asks :func:`_bindings` rather than sweeping for binding forms
    itself. A pinned name may be bound only by an import, a ``class``/``def``,
    or an assignment whose value is a type expression over already-vetted
    names. **Every other binding construct is refused**, including ones nobody
    thought to list: walrus, tuple-unpack, ``for`` target, ``with ... as``,
    ``except ... as``, a parameter, ``global``, and ``match``/``case``
    capture. That last one is why this reads the shared oracle: it was the
    fourth spelling of this same escape, and a fifth would have been next.
    """
    pinned = _PURE_ANNOTATIONS[rel]
    vetted = pinned | _PURE_BUILTINS[rel]

    offenders: set[str] = set()
    for name, node in _bindings(tree):
        if name not in pinned or isinstance(node, _SAFE_BINDING_NODES):
            continue
        if (
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and node.value is not None
            and _is_type_expression(node.value, vetted)
        ):
            continue
        offenders.add(name)
    return sorted(offenders)


def _annotation_attributes(tree: ast.Module) -> list[str]:
    """Dotted annotations, e.g. ``x: mod.Thing``.

    None exist in either pure source. A dotted annotation would let a pinned
    base name carry an unpinned attribute past :func:`_annotation_names`, so
    it is refused rather than resolved.
    """
    return [
        node.attr
        for annotation in _annotation_nodes(tree)
        for node in ast.walk(annotation)
        if isinstance(node, ast.Attribute)
    ]


def _delta(actual: set[Any], pinned: set[Any]) -> tuple[list[Any], list[Any]]:
    """``(present but unpinned, pinned but absent)`` — empty both ways or bust.

    Shared by all three set comparisons in this file so the "both directions"
    property is proven once, in
    :func:`test_delta_reports_both_directions`, rather than asserted three
    times and tested nowhere. The second half is the one that gets dropped: a
    speculatively widened pin — someone adding ``open`` to
    :data:`_PURE_BUILTINS` "for later" — must redden as *pinned but absent*
    rather than sit green and pre-authorised.
    """
    return sorted(actual - pinned), sorted(pinned - actual)


def _pinned_pairs(rel: str) -> set[tuple[str, str]]:
    """One source's :data:`_PURE_IMPORTS` entry, flattened to pairs."""
    return {
        (module, symbol)
        for module, symbols in _PURE_IMPORTS[rel].items()
        for symbol in symbols
    }


@pytest.mark.parametrize("rel", _PURE_SOURCES)
def test_pure_seam_modules_import_only_pinned_symbols(rel: str) -> None:
    """Pinned per source, BOTH directions: an added import reddens, a removed one too."""
    added, dropped = _delta(_imported_symbols(rel, _tree(rel)), _pinned_pairs(rel))

    assert not added and not dropped, (
        f"{rel}'s import set drifted from its pin.\n"
        f"  added:   {added}\n"
        f"  dropped: {dropped}\n"
        f"A pair whose symbol is {_WHOLE_MODULE!r} is a bare `import x`; rewrite "
        "it as `from x import <name>` so the pin can see what was taken.\n"
        "If the engine now needs to read something, the read belongs in "
        "policy.facts (a collector), not here — see epic #11752."
    )


@pytest.mark.parametrize("rel", _PURE_SOURCES)
def test_pure_seam_modules_use_only_pinned_builtins(rel: str) -> None:
    """The import pin is blind to builtins, so they get their own allow-list.

    Pinned per source in both directions, like the imports: an unrecognised
    builtin is the signal, and it does not matter whether it is a dangerous one.
    """
    added, dropped = _delta(_free_names(_tree(rel)), set(_PURE_BUILTINS[rel]))

    assert not added and not dropped, (
        f"{rel}'s builtin usage drifted from its pin.\n"
        f"  added:   {added}\n"
        f"  dropped: {dropped}\n"
        "An added name reached the module without an import — that is how "
        "open(), __import__(), exec(), eval(), compile(), __builtins__ and "
        "__file__ get in. If it genuinely cannot reach the world, add that one "
        "name to this file's _PURE_BUILTINS entry; if it can, the read belongs "
        "in policy.facts."
    )


@pytest.mark.parametrize("rel", _PURE_SOURCES)
def test_pure_seam_modules_never_shadow_a_builtin(rel: str) -> None:
    """A shadowing binding would blind the builtin pin above.

    ``eval = eval`` binds ``eval``, so :func:`_free_names` stops reporting it
    and every later ``eval(...)`` passes unseen. Refusing all shadowing closes
    that without a list of dangerous names to keep current.
    """
    offenders = _shadowed_builtins(_tree(rel))

    assert not offenders, (
        f"{rel} binds {offenders}, which shadow a builtin or a module dunder. "
        "Rename the binding: a shadowed name stops "
        "test_pure_seam_modules_use_only_pinned_builtins from seeing it used "
        "at all. For a pydantic field this is a schema decision, not a local "
        "rename — but the alternative is a pin that cannot see that name."
    )


@pytest.mark.parametrize("rel", _PURE_SOURCES)
def test_pure_seam_annotations_name_only_pinned_types(rel: str) -> None:
    """Annotations are ``eval``-ed by pydantic, so their vocabulary is pinned.

    Both directions, like every other pin. This is the rule; the two tests
    below are the shapes it cannot express as a name.
    """
    added, dropped = _delta(_annotation_names(_tree(rel)), set(_PURE_ANNOTATIONS[rel]))

    assert not added and not dropped, (
        f"{rel}'s annotation vocabulary drifted from its pin.\n"
        f"  added:   {added}\n"
        f"  dropped: {dropped}\n"
        "Pydantic resolves annotations with eval() against module globals, so "
        "an annotation naming a local is executable code rules 1-2 cannot "
        "read. If the added name is a genuine type, pin it here; if it is a "
        "string being smuggled into eval, that is the thing this refuses."
    )


@pytest.mark.parametrize("rel", _PURE_SOURCES)
def test_pure_seam_annotation_types_are_not_rebound(rel: str) -> None:
    """The other half of rule 4: what a pinned name is *bound to*.

    Naming a pinned type is not enough if the name itself can be rebound to a
    string — pydantic evaluates whatever it resolves to.
    """
    offenders = _rebound_annotation_names(rel, _tree(rel))

    assert not offenders, (
        f"{rel} rebinds annotation type(s) {offenders} to something that is "
        "not a type expression. Pydantic evaluates whatever the name resolves "
        "to at class-creation time, so a rebound annotation name is executable "
        "code the vocabulary pin cannot see. A type alias may only be built "
        "from names, dots, subscripts, unions and tuples."
    )


@pytest.mark.parametrize("rel", _PURE_SOURCES)
def test_pure_seam_modules_have_no_dotted_annotations(rel: str) -> None:
    """``x: N.A`` would carry an unpinned attribute past a pinned base name."""
    offenders = _annotation_attributes(_tree(rel))

    assert not offenders, (
        f"{rel} carries dotted annotation(s) {offenders}. Only the base name is "
        "pinned, so the attribute rides in unchecked. Import the type and name "
        "it directly."
    )


@pytest.mark.parametrize("rel", _PURE_SOURCES)
def test_pure_seam_modules_have_no_string_annotations(rel: str) -> None:
    """A quoted annotation is a string that never appears as a name."""
    offenders = _string_annotations(_tree(rel))

    assert not offenders, (
        f"{rel} carries string annotation(s) {offenders}. Pydantic resolves "
        "these with eval() against module globals, so they are executable code "
        "no static pin above can read. The file imports `annotations` from "
        "__future__, so drop the quotes."
    )


def test_every_policy_module_is_classified() -> None:
    """A new module in ``src/policy/`` must not arrive silently unguarded.

    :data:`_PURE_SOURCES` is itself a list, and an unlisted file is exactly
    the quiet failure the rest of this file exists to prevent: add
    ``src/policy/engine_helpers.py`` today and nothing above would look at it.
    Requiring every module to be classified as pure *or* I/O puts that list on
    the loud side — a new module reddens here until someone says which half of
    the seam it belongs to.
    """
    on_disk = {
        path.relative_to(REPO).as_posix()
        for path in (REPO / _POLICY_PACKAGE).rglob("*.py")
    }
    unclassified, missing = _delta(on_disk, set(_PURE_SOURCES) | set(_IO_SOURCES))

    assert not unclassified and not missing, (
        f"{_POLICY_PACKAGE}/ and this guard's lists disagree.\n"
        f"  unclassified on disk: {unclassified}\n"
        f"  listed but missing:   {missing}\n"
        "A new module is unguarded until it is listed. If it is part of the "
        "decision engine add it to _PURE_IMPORTS and _PURE_BUILTINS (and "
        "expect both pins to redden until its needs are pinned); if it reads "
        "the world it is a collector and belongs in _IO_SOURCES."
    )


def test_the_guard_is_looking_at_real_files() -> None:
    """Anti-vacuity: a renamed module must not make this file pass over nothing."""
    for rel in _PURE_SOURCES:
        assert (REPO / rel).is_file(), f"{rel} is missing — the guard sees nothing"
        assert _imported_symbols(rel, _tree(rel)), f"{rel} imports nothing"
        assert _PURE_BUILTINS[rel], f"{rel} has an empty builtin pin"


# --------------------------------------------------------------------------- #
# The analyzers' own power, pinned. Without these, a bug in a helper above     #
# would silently retire a rule and every test in this file would stay green —  #
# the exact failure mode the whole file exists to prevent.                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source", "bound"),
    [
        pytest.param("x = 1", "x", id="assignment"),
        pytest.param("def f(): pass", "f", id="def"),
        pytest.param("class C: pass", "C", id="class"),
        pytest.param("def f(arg): return arg", "arg", id="parameter"),
        pytest.param("import os.path as p\np", "p", id="import-alias"),
        pytest.param("import os.path\nos", "os", id="dotted-bare-import"),
        pytest.param("for i in ():\n    print(i)", "i", id="for-target"),
        pytest.param("with ctx() as fh:\n    fh", "fh", id="with-as"),
        pytest.param("[y for y in ()]", "y", id="comprehension"),
        pytest.param("(w := 1)\nw", "w", id="walrus"),
        pytest.param(
            "try:\n    pass\nexcept E as err:\n    err", "err", id="except-as"
        ),
        pytest.param("def f():\n    global gv\n    return gv", "gv", id="global"),
        pytest.param(
            "match d:\n    case str() as cap:\n        cap", "cap", id="match-as"
        ),
        pytest.param(
            "match d:\n    case [a, *rest]:\n        rest", "rest", id="match-star"
        ),
        pytest.param(
            "match d:\n    case {'k': v, **extra}:\n        extra",
            "extra",
            id="match-mapping-rest",
        ),
    ],
)
def test_bound_names_sees_every_binding_form(source: str, bound: str) -> None:
    """A binding form the analyzer cannot see becomes a FALSE RED.

    The name looks free, is not in :data:`_PURE_BUILTINS`, and legitimate code
    fails the builtin pin. The ``match`` forms are the easy ones to miss:
    ``MatchAs.name``, ``MatchStar.name`` and ``MatchMapping.rest`` are plain
    string attributes, so ``ast.walk`` never yields them as ``ast.Name``.
    """
    assert bound in _bound_names(ast.parse(source))
    assert bound not in _free_names(ast.parse(source))


def test_del_does_not_count_as_a_binding() -> None:
    """``del`` unbinds; counting it as a binding was a demonstrated escape.

    ``ROOT = __file__`` then ``del __file__`` reads the module's path and then
    cancels the ``Load`` that rule 2 keys on. The engine ends up with a root
    and the guard stays green.
    """
    smuggled = "ROOT = __file__\ndel __file__"
    assert "__file__" in _free_names(ast.parse(smuggled))

    # ...while a genuine local is still bound by its Store, so no false red.
    assert "tmp" not in _free_names(ast.parse("tmp = 1\ndel tmp"))


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('__import__("subprocess").run(["git"])', id="dunder-import"),
        pytest.param('exec("import os")', id="exec"),
        pytest.param("eval(\"__import__('os')\")", id="eval"),
        pytest.param('compile("x", "<s>", "exec")', id="compile"),
        pytest.param('open("/etc/passwd").read()', id="open"),
        pytest.param("ROOT = __file__", id="dunder-file"),
        pytest.param('_OPEN = __builtins__["open"]', id="dunder-builtins"),
        pytest.param("globals()['os']", id="globals"),
        pytest.param("vars()", id="vars"),
    ],
)
def test_builtin_pin_sees_import_free_world_reads(source: str) -> None:
    """Rule 2's power, pinned directly."""
    free = _free_names(ast.parse(source))
    assert free - set().union(*_PURE_BUILTINS.values()), (
        f"{source!r} produced no un-pinned free name"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from policy.store import append_facts",
            ("policy.store", "append_facts"),
            id="absolute-sibling",
        ),
        pytest.param(
            "from .store import append_facts",
            ("policy.store", "append_facts"),
            id="relative-sibling",
        ),
        pytest.param(
            "from adr_conformance import live_debt",
            ("adr_conformance", "live_debt"),
            id="repo-reading-symbol",
        ),
        pytest.param(
            "from adr_conformance import live_debt as CheckOutcome",
            ("adr_conformance", "live_debt"),
            id="aliased-onto-a-pinned-name",
        ),
        pytest.param(
            "import subprocess",
            ("subprocess", _WHOLE_MODULE),
            id="bare-import",
        ),
    ],
)
def test_import_pin_resolves_to_module_and_symbol(
    source: str, expected: tuple[str, str]
) -> None:
    """Dotted module *and* source symbol, so neither half can hide behind the other.

    ``policy.store`` must not collapse to ``policy``, ``live_debt`` must not
    hide inside ``adr_conformance``, and renaming it to ``CheckOutcome`` on the
    way in must not land it on a pinned pair.
    """
    rel = "src/policy/python_engine.py"
    assert expected in _imported_symbols(rel, ast.parse(source))
    assert expected not in _pinned_pairs(rel)


def test_import_pin_refuses_a_relative_import_above_the_package() -> None:
    """Resolving one would invent a name that may collide with a pinned module.

    ``from ..adr_conformance import CheckOutcome`` inside ``policy`` is an
    ImportError in CPython, but naive arithmetic resolves it to the *pinned*
    ``adr_conformance`` — silently wrong in the permissive direction.
    """
    with pytest.raises(AssertionError, match="above the top-level package"):
        _imported_symbols(
            "src/policy/python_engine.py",
            ast.parse("from ..adr_conformance import CheckOutcome"),
        )


@pytest.mark.parametrize(
    "name",
    ["open", "eval", "exec", "compile", "__import__", "__file__", "__builtins__"],
)
def test_forbidden_bindings_covers_what_rule_two_depends_on(name: str) -> None:
    """Rule 3 is only as good as its forbidden set.

    ``__file__`` and ``__builtins__`` are NOT in ``dir(builtins)`` — the
    builtins module is compiled in and has neither attribute — so a set built
    from ``dir(builtins)`` alone leaves a hole exactly where rule 2 matters
    most.
    """
    assert name in _forbidden_bindings()
    assert _shadowed_builtins(ast.parse(f"{name} = 1")) == [name]


def test_delta_reports_both_directions() -> None:
    """All three pins share this; weakening it to a subset check is the risk.

    The *pinned but absent* half is the one that gets dropped, and it is the
    half that refuses a speculatively widened pin — an entry nobody uses,
    sitting green, pre-authorising the thing it names.
    """
    assert _delta({"a"}, {"a"}) == ([], [])
    assert _delta({"a", "extra"}, {"a"}) == (["extra"], [])
    assert _delta({"a"}, {"a", "unused"}) == ([], ["unused"])


def test_forbidden_bindings_covers_every_module_dunder() -> None:
    """:data:`_MODULE_DUNDERS` is hand-written, so derive the truth and compare.

    A hand-list rots silently — this file shipped one draft claiming the set
    was "closed" while missing ``__cached__`` (the ``.pyc`` path, three
    ``parents`` from the repo root) and ``__annotations__``. Reading the
    dunders off live modules puts that list on the loud side: the next
    interpreter to add one reddens here instead of opening a hole in rule 3.
    """
    probes = [ast, sys.modules[__name__]]
    for module in probes:
        module.__annotations__  # noqa: B018 - materialises the lazy attribute
    observed = {
        name
        for module in probes
        for name in vars(module)
        if name.startswith("__") and name.endswith("__")
    }

    missing = sorted(observed - _forbidden_bindings())
    assert not missing, (
        f"the import system injects {missing}, which no pure source may bind "
        "but _MODULE_DUNDERS does not list. Add them: an unlisted module "
        "dunder can be shadowed, and a shadowed name is one rule 2 stops "
        "seeing entirely."
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("_A = 'int'\nx: _A = 1", id="assigned-literal"),
        pytest.param("(_A := 'int')\nx: _A = 1", id="walrus"),
        pytest.param("_A = 'in' + 't'\nx: _A = 1", id="concatenated"),
        pytest.param("_A = 'int'\n_B = _A\nx: _B = 1", id="chained-alias"),
        pytest.param("(_A,) = ('int',)\nx: _A = 1", id="tuple-unpack"),
        pytest.param("for _A in ('int',):\n    pass\nx: _A = 1", id="for-target"),
        pytest.param("_A = ''.join(['i'])\nx: _A = 1", id="computed"),
        pytest.param("class N:\n    A = 'int'\nx: N.A = 1", id="attribute"),
    ],
)
def test_annotation_vocabulary_refuses_every_smuggled_name(source: str) -> None:
    """The reason rule 4 is a vocabulary pin and not a shape denylist.

    Each of these binds a string and annotates with it, reaching pydantic's
    ``eval``. A rule that denied one AST shape let the next seven through —
    the "patch the spelling" failure this file is otherwise built to avoid.
    Naming the allowed vocabulary refuses all eight identically, because none
    of ``_A``/``_B``/``N`` is a pinned type.
    """
    tree = ast.parse(source)
    pinned = set().union(*_PURE_ANNOTATIONS.values())

    assert _annotation_names(tree) - pinned or _annotation_attributes(tree), (
        f"{source!r} smuggled a name past the annotation vocabulary"
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('Fact = "<expr>"', id="plain-rebind"),
        pytest.param('(Fact := "<expr>")', id="walrus-rebind"),
        pytest.param('Fact = "".join(["x"])', id="computed-rebind"),
        pytest.param('(Fact,) = ("<expr>",)', id="tuple-unpack-rebind"),
        pytest.param('for Fact in ("<expr>",):\n    pass', id="for-target-rebind"),
        pytest.param("with ctx() as Fact:\n    pass", id="with-as-rebind"),
    ],
)
def test_rebinding_a_pinned_annotation_type_is_refused(source: str) -> None:
    """A name on the pin is only as good as what it is bound to."""
    rel = "src/policy/models.py"
    assert _rebound_annotation_names(rel, ast.parse(source)) == ["Fact"]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('_X = "<expr>"\nFact = _X', id="one-hop-alias"),
        pytest.param('_X = "<expr>"\nFact = _X | None', id="alias-in-a-union"),
        pytest.param('_X = "<expr>"\nFact = list[_X]', id="alias-in-a-subscript"),
        pytest.param('_X = "<expr>"\nFact = (_X,)', id="alias-in-a-tuple"),
        pytest.param("Fact = _Unvetted", id="bare-unvetted-name"),
        pytest.param(
            "Fact = DecisionStatus.SUPERSEDED", id="attribute-off-a-vetted-base"
        ),
        pytest.param("Fact = str.__doc__", id="attribute-off-a-builtin"),
        pytest.param(
            "match p:\n    case Fact:\n        pass", id="match-capture-rebind"
        ),
        pytest.param(
            "match p:\n    case [*Fact]:\n        pass", id="match-star-rebind"
        ),
        pytest.param(
            "match p:\n    case {**Fact}:\n        pass", id="match-mapping-rebind"
        ),
        pytest.param("def _f():\n    global Fact\n    Fact = 1", id="global-rebind"),
        pytest.param("try:\n    pass\nexcept E as Fact:\n    pass", id="except-as"),
        pytest.param("def _f(Fact):\n    return Fact", id="parameter-shadow"),
    ],
)
def test_a_type_alias_may_only_name_vetted_types(source: str) -> None:
    """The grammar check alone is satisfied one hop up the chain.

    ``Fact = _X`` is a single ``Name`` — a perfectly well-formed type
    expression — while ``_X`` holds the payload. Requiring every name in the
    alias to be pinned already is what stops the smuggling moving upstream.
    """
    rel = "src/policy/models.py"
    assert _rebound_annotation_names(rel, ast.parse(source)) == ["Fact"]


def test_a_real_type_alias_is_still_allowed() -> None:
    """Anti-vacuity for the rebinding rule: real aliases must stay legal.

    ``models.py`` genuinely defines ``FactValue = bool | int | float | str``.
    """
    rel = "src/policy/models.py"
    assert _rebound_annotation_names(rel, ast.parse("FactValue = bool | int")) == []
    assert (
        _rebound_annotation_names(rel, ast.parse("FactValue = list[str] | None")) == []
    )
    assert _rebound_annotation_names(rel, ast.parse("Unpinned = 'anything'")) == []


def test_annotation_vocabulary_accepts_the_real_types() -> None:
    """Anti-vacuity: the rule must not simply reject everything."""
    assert not _annotation_names(ast.parse("x: int = 1")) - {"int"}
    assert _annotation_attributes(ast.parse("x: int = 1")) == []
    # A dotted annotation on a PINNED base is what this helper alone catches:
    # `Fact` is on the vocabulary pin, so nothing else would report `Fact.A`.
    assert _annotation_attributes(ast.parse("x: Fact.A = 1")) == ["A"]
    # A string constant that never annotates anything stays legal: the pure
    # sources legitimately hold tuples of required fact keys.
    assert _string_annotations(ast.parse('REQUIRED = ("a", "b")\nx: int = 1')) == []


def test_string_annotation_rule_sees_a_quoted_annotation() -> None:
    """Rule 4's power, pinned — including one nested inside a subscript."""
    assert _string_annotations(ast.parse("x: 'int' = 1")) == ["int"]
    assert sorted(_string_annotations(ast.parse("def f(a: 'A') -> 'B': ..."))) == [
        "A",
        "B",
    ]
    assert _string_annotations(ast.parse("x: list['Deferred'] = []")) == ["Deferred"]
    assert _string_annotations(ast.parse("x: int = 1")) == []
