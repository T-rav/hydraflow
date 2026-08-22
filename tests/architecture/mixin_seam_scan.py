"""AST class-graph scan for the mixin seam-stub shadowing trap (#11629).

Support code for ``tests/architecture/test_mixin_seam_stub_shadowing.py`` and
its regression story
(``tests/regressions/test_issue_11629_mixin_seam_stub_shadowing.py``). Pure
functions only — the tree is read from disk and parsed, never imported, so a
module with import-time side effects (or one that cannot import in a bare
environment) is still analysable.

The house god-class recipe is "extract a cohesive cluster into a mixin module
and have the host class inherit it". A mixin needs to reference collaborators
it does not own, and the tempting way to declare that seam is a runtime stub::

    class SeamMixin:
        async def _run_gh(self, *cmd: str) -> str: ...  # provided by the host

With exactly ONE mixin that is safe: the host's real definition always precedes
the mixin in ``__mro__``. With two or more it is not. Attribute lookup walks
``__mro__`` left to right and stops at the FIRST class carrying the name, so a
stub in an earlier mixin wins over a *sibling* mixin's real implementation. A
``...`` body returns ``None``, so the failure is silent.

Two orthogonal scans over ``src/**/*.py``:

1. :func:`scan_shadowed_seams` — the trap itself. Reconstructs each class's
   real C3 linearization and reports every name whose winning definition is a
   stub (``...`` or ``pass``) while a LATER entry in the same MRO provides a
   real body. Zero false positives by construction: this is the bug.

2. :func:`scan_runtime_method_seams` — the structural rule that keeps scan 1
   from ever having something to find. Any class in ``src/`` that another
   ``src/`` class inherits must declare its method seams under
   ``if TYPE_CHECKING:``, so no runtime attribute exists to shadow anything.
   ``Protocol`` and ``abc.ABC`` subclasses are exempt: ``...`` is the idiom
   there, and an unimplemented abstract method fails loudly at instantiation.

Attribute *annotations* (``_config: HydraFlowConfig``) are safe unguarded and
are not touched by either scan — a bare annotation creates no class attribute.

Known scope limits. Every one of these makes the scans MISS a case, never
invent one, so a green run is a weaker claim than it looks but is never a false
accusation:

* only module-level classes are graphed — a class nested in a function or in
  another class is invisible (no such mixin exists in ``src/`` today);
* a base reached through a re-export (``from pr_manager import SomeMixin``
  where the class is really defined in ``pr_manager_promotion``) resolves to a
  key that does not exist, so that edge is dropped;
* :func:`_import_map` walks the whole module with :func:`ast.walk` and is
  therefore scope-unaware: a deferred, function-local import of the same name
  can overwrite the module-level binding used to resolve a base;
* :func:`_collect_methods` recognises only ``if TYPE_CHECKING:`` as a
  non-runtime block — a method defined under any other conditional is treated
  as runtime code (which is the conservative reading).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Decorators whose ``...`` body is a typing construct rather than a seam stub.
# ``overload`` is additionally neutralised by last-definition-wins resolution.
_TYPING_DECORATORS = frozenset({"overload", "abstractmethod", "abstractproperty"})

# Base spellings that mark a class as protocol/abstract — ``...`` is the idiom.
_PROTOCOL_BASES = frozenset(
    {"Protocol", "typing.Protocol", "typing_extensions.Protocol"}
)
_ABSTRACT_BASES = frozenset({"ABC", "abc.ABC"})


@dataclass(frozen=True)
class MethodDecl:
    """One ``def``/``async def`` in a class body."""

    name: str
    lineno: int
    stub: str | None
    """``"..."`` / ``"pass"`` for a stub body, ``None`` for a real body."""
    decorators: frozenset[str]
    type_checking_only: bool


@dataclass(frozen=True)
class ClassDecl:
    """One module-level ``class`` statement in ``src/``."""

    key: str
    """``"<dotted module>:<ClassName>"`` — unique across the tree."""
    name: str
    relpath: str
    lineno: int
    base_exprs: tuple[str, ...]
    methods: tuple[MethodDecl, ...]

    def runtime_method(self, name: str) -> MethodDecl | None:
        """The definition of *name* this class actually contributes at runtime.

        Last definition wins, matching Python's own class-body semantics — that
        is what makes an ``@overload`` chain resolve to its implementation.
        """
        winner: MethodDecl | None = None
        for method in self.methods:
            if method.name == name and not method.type_checking_only:
                winner = method
        return winner


@dataclass(frozen=True)
class ShadowedSeam:
    """A seam stub that wins the MRO over a sibling's real implementation."""

    host: str
    method: str
    stub_owner: str
    stub_relpath: str
    stub_lineno: int
    impl_owner: str
    impl_relpath: str
    impl_lineno: int

    def describe(self) -> str:
        """One-line offender rendering for an assertion message."""
        return (
            f"{self.host}.{self.method} resolves to the {self.stub_owner} stub at "
            f"{self.stub_relpath}:{self.stub_lineno}, shadowing the real "
            f"{self.impl_owner} implementation at "
            f"{self.impl_relpath}:{self.impl_lineno}"
        )


@dataclass(frozen=True)
class RuntimeSeam:
    """A runtime ``...`` method stub on a class that something inherits."""

    owner: str
    method: str
    relpath: str
    lineno: int

    def describe(self) -> str:
        """One-line offender rendering for an assertion message."""
        return (
            f"{self.relpath}:{self.lineno} — {self.owner}.{self.method} is a runtime "
            "`...` seam stub; move it under `if TYPE_CHECKING:`"
        )


def _stub_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return ``"..."`` / ``"pass"`` if *node*'s body is a bare stub, else ``None``."""
    body = [
        stmt
        for stmt in node.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if len(body) != 1:
        return None
    only = body[0]
    if isinstance(only, ast.Pass):
        return "pass"
    if (
        isinstance(only, ast.Expr)
        and isinstance(only.value, ast.Constant)
        and only.value.value is Ellipsis
    ):
        return "..."
    return None


def _is_type_checking_test(test: ast.expr) -> bool:
    """True for ``if TYPE_CHECKING:`` in either the bare or dotted spelling."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    names: set[str] = set()
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return frozenset(names)


def _collect_methods(body: list[ast.stmt], *, type_checking: bool) -> list[MethodDecl]:
    """Flatten a class body into method declarations, tracking TYPE_CHECKING depth."""
    methods: list[MethodDecl] = []
    for stmt in body:
        if isinstance(stmt, ast.If) and _is_type_checking_test(stmt.test):
            methods.extend(_collect_methods(stmt.body, type_checking=True))
            methods.extend(_collect_methods(stmt.orelse, type_checking=type_checking))
        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            methods.append(
                MethodDecl(
                    name=stmt.name,
                    lineno=stmt.lineno,
                    stub=_stub_kind(stmt),
                    decorators=_decorator_names(stmt),
                    type_checking_only=type_checking,
                )
            )
    return methods


@dataclass(frozen=True)
class _Module:
    """One parsed ``src/`` module: its dotted name, tree, and package-ness."""

    name: str
    relpath: str
    tree: ast.Module
    is_package: bool
    """True for ``__init__.py`` — a relative import there starts at itself."""


def _load_modules(repo_root: Path) -> list[_Module]:
    """Parse every ``src/**/*.py`` once; both scans share the result."""
    src_root = repo_root / "src"
    modules: list[_Module] = []
    for path in sorted(src_root.rglob("*.py")):
        parts = list(path.relative_to(src_root).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        modules.append(
            _Module(
                name=".".join(parts),
                relpath=str(path.relative_to(repo_root)),
                tree=ast.parse(path.read_text(encoding="utf-8")),
                is_package=is_package,
            )
        )
    return modules


def _resolve_relative(module: _Module, level: int, tail: str | None) -> str:
    """Resolve ``from ..pkg import X`` against the importing *module*.

    Level 1 anchors at the module's own package: that is *itself* for an
    ``__init__.py`` and its parent for a plain submodule. Each extra dot climbs
    one further.
    """
    parts = module.name.split(".") if module.name else []
    if not module.is_package:
        parts = parts[:-1]
    climb = level - 1
    base = parts[: len(parts) - climb] if climb <= len(parts) else []
    if tail:
        base = [*base, *tail.split(".")]
    return ".".join(base)


def _import_map(module: _Module) -> dict[str, str]:
    """Local name -> ``"<module>:<Name>"`` for every ``from ... import`` binding."""
    mapping: dict[str, str] = {}
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        origin = (
            _resolve_relative(module, node.level, node.module)
            if node.level
            else (node.module or "")
        )
        for alias in node.names:
            if alias.name != "*":
                mapping[alias.asname or alias.name] = f"{origin}:{alias.name}"
    return mapping


def _base_key(
    base_expr: str, *, module: str, imports: dict[str, str], known: set[str]
) -> str | None:
    """Resolve a base expression to a class key, or ``None`` if it is external."""
    # ``Base[T]`` / ``Base[T, U]`` -> ``Base``.
    stem = base_expr.split("[", 1)[0].strip()
    local = f"{module}:{stem}"
    if local in known:
        return local
    imported = imports.get(stem)
    if imported in known:
        return imported
    if "." in stem:
        dotted_module, _, name = stem.rpartition(".")
        # ``import state.gc`` then ``state.gc.Mixin``, or an aliased package.
        candidate = f"{dotted_module}:{name}"
        if candidate in known:
            return candidate
        aliased = imports.get(dotted_module)
        if aliased and aliased.split(":", 1)[0]:
            head = aliased.replace(":", ".")
            if f"{head}:{name}" in known:
                return f"{head}:{name}"
    return None


def _classes_of(modules: list[_Module]) -> dict[str, ClassDecl]:
    classes: dict[str, ClassDecl] = {}
    for module in modules:
        for node in module.tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            key = f"{module.name}:{node.name}"
            classes[key] = ClassDecl(
                key=key,
                name=node.name,
                relpath=module.relpath,
                lineno=node.lineno,
                base_exprs=tuple(ast.unparse(b) for b in node.bases),
                methods=tuple(_collect_methods(node.body, type_checking=False)),
            )
    return classes


def _bases_of(
    modules: list[_Module], classes: dict[str, ClassDecl]
) -> dict[str, tuple[tuple[str | None, str], ...]]:
    known = set(classes)
    by_module: dict[str, list[ClassDecl]] = {}
    for key, decl in classes.items():
        by_module.setdefault(key.split(":", 1)[0], []).append(decl)

    resolved: dict[str, tuple[tuple[str | None, str], ...]] = {}
    for module in modules:
        imports = _import_map(module)
        for decl in by_module.get(module.name, ()):
            resolved[decl.key] = tuple(
                (
                    _base_key(expr, module=module.name, imports=imports, known=known),
                    expr,
                )
                for expr in decl.base_exprs
            )
    return resolved


def collect_classes(repo_root: Path) -> dict[str, ClassDecl]:
    """Parse every module-level class under ``<repo_root>/src`` into a graph."""
    return _classes_of(_load_modules(repo_root))


def _linearize(
    classes: dict[str, ClassDecl],
    bases: dict[str, tuple[tuple[str | None, str], ...]],
) -> dict[str, list[str]]:
    """Real C3 MRO per class, computed by mirroring the graph into real types.

    Bases outside ``src/`` (``Protocol``, ``BaseModel``, …) are dropped rather
    than guessed. Dropping them can only hide a shadowing pair, never invent
    one, which keeps both scans free of false positives.
    """
    built: dict[str, type] = {}
    key_of: dict[type, str] = {}

    def build(key: str, stack: frozenset[str]) -> type | None:
        if key in built:
            return built[key]
        if key in stack:
            return None  # import cycle in the mirrored graph — unanalysable
        parents: list[type] = []
        for resolved_key, _expr in bases.get(key, ()):
            if resolved_key is None:
                continue
            parent = build(resolved_key, stack | {key})
            if parent is not None and parent not in parents:
                parents.append(parent)
        try:
            made = type(classes[key].name, tuple(parents), {})
        except TypeError:
            return None  # inconsistent linearization — nothing to say about it
        built[key] = made
        key_of[made] = key
        return made

    mros: dict[str, list[str]] = {}
    for key in classes:
        made = build(key, frozenset())
        if made is None:
            continue
        mros[key] = [key_of[entry] for entry in made.__mro__ if entry in key_of]
    return mros


def scan_shadowed_seams(repo_root: Path) -> list[ShadowedSeam]:
    """Every name whose MRO winner is a stub while a later entry implements it."""
    modules = _load_modules(repo_root)
    classes = _classes_of(modules)
    mros = _linearize(classes, _bases_of(modules, classes))

    offenders: list[ShadowedSeam] = []
    for host_key, mro in sorted(mros.items()):
        if len(mro) < 2:  # noqa: PLR2004 — a lone class shadows nothing
            continue
        names = {
            method.name
            for key in mro
            for method in classes[key].methods
            if not method.type_checking_only
        }
        for name in sorted(names):
            winner: tuple[str, MethodDecl] | None = None
            impl: tuple[str, MethodDecl] | None = None
            for key in mro:
                decl = classes[key].runtime_method(name)
                if decl is None:
                    continue
                if winner is None:
                    winner = (key, decl)
                elif decl.stub is None and impl is None:
                    impl = (key, decl)
            if winner is None or impl is None or winner[1].stub is None:
                continue
            if winner[1].decorators & _TYPING_DECORATORS:
                continue  # abstract/overload — loud at instantiation, not silent
            offenders.append(
                ShadowedSeam(
                    host=classes[host_key].name,
                    method=name,
                    stub_owner=classes[winner[0]].name,
                    stub_relpath=classes[winner[0]].relpath,
                    stub_lineno=winner[1].lineno,
                    impl_owner=classes[impl[0]].name,
                    impl_relpath=classes[impl[0]].relpath,
                    impl_lineno=impl[1].lineno,
                )
            )
    return offenders


def _exempt_keys(
    classes: dict[str, ClassDecl],
    bases: dict[str, tuple[tuple[str | None, str], ...]],
) -> set[str]:
    """Class keys that are Protocols or ABCs, transitively — ``...`` is fine there."""
    exempt: set[str] = set()
    changed = True
    while changed:
        changed = False
        for key in classes:
            if key in exempt:
                continue
            for resolved_key, expr in bases.get(key, ()):
                stem = expr.split("[", 1)[0].strip()
                if (
                    stem in _PROTOCOL_BASES
                    or stem in _ABSTRACT_BASES
                    or (resolved_key is not None and resolved_key in exempt)
                ):
                    exempt.add(key)
                    changed = True
                    break
    return exempt


def scan_runtime_method_seams(repo_root: Path) -> list[RuntimeSeam]:
    """Every runtime ``...`` method stub on a class that another src class inherits."""
    modules = _load_modules(repo_root)
    classes = _classes_of(modules)
    bases = _bases_of(modules, classes)
    exempt = _exempt_keys(classes, bases)
    inherited = {
        resolved_key
        for pairs in bases.values()
        for resolved_key, _expr in pairs
        if resolved_key is not None
    }

    offenders: list[RuntimeSeam] = []
    for key in sorted(inherited - exempt):
        decl = classes[key]
        for method in decl.methods:
            if method.type_checking_only or method.stub != "...":
                continue
            if method.decorators & _TYPING_DECORATORS:
                continue
            if decl.runtime_method(method.name) is not method:
                continue  # superseded later in the same class body
            offenders.append(
                RuntimeSeam(
                    owner=decl.name,
                    method=method.name,
                    relpath=decl.relpath,
                    lineno=method.lineno,
                )
            )
    return offenders
