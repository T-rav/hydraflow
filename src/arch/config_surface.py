"""The config surface: every module ``HydraFlowConfig`` is spread across.

Three arch readers derive published artifacts from ``src/config.py`` by
parsing it as a *file*: the loop registry's tick intervals, the AI system
inventory's role table, and its model-role attribution. Each one assumed the
whole config lives in that one file's text.

That assumption is what has kept ``src/config.py`` a god file. Decomposing it
— moving field groups onto base classes, or the ``_ENV_*_OVERRIDES`` tables to
a sibling module — is the standing remedy in #11547, and every one of those
readers answered **empty** rather than raising when it was tried:

===================================  ==============  ================
reader                               monolithic      decomposed
===================================  ==============  ================
role table (``_ENV_COMBO_OVERRIDES``) 1 row          ``[]``
``*_model`` field names               2 names        ``[]``
int field defaults                    1 default      ``{}``
===================================  ==============  ================

No exception, no CI failure — a blank "Model roles" table on the Pages site
and loop intervals quietly unresolvable. This is the "stops seeing its subject
when the code moves" failure that #11673 hit in a guard and that
``resolve_local_module`` below already hardens for packages, one level up: the
subject here is not a package, it is a *class body*.

So the surface is named once, here, and the readers ask it questions instead
of reading a path. It spans ``src/config.py`` plus the src-local modules that
file imports, and class lookups follow base classes across all of it.

Pure AST reads, no imports of the live config: an arch extractor may not have
side effects, and importing ``config`` would resolve paths and read the
environment.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__ = [
    "annotated_field_names",
    "config_surface_paths",
    "int_field_defaults",
    "local_imports",
    "parse_tree",
    "resolve_local_module",
    "role_table",
]

#: The role registry the AI system inventory renders.
ROLE_TABLE_NAME = "_ENV_COMBO_OVERRIDES"


def parse_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def resolve_local_module(dotted: str, src_dir: Path) -> list[Path]:
    """Every file *dotted* names: one module, or a whole package.

    A package resolves to ALL of its modules, not just ``__init__.py``. Under
    the god-class recipe (#11547) a decomposed module's ``__init__`` is a
    re-export facade with no logic left in it, so resolving it to that facade
    alone shrinks the caller's scan to nothing (#11673).
    """
    parts = dotted.split(".")
    as_file = src_dir.joinpath(*parts).with_suffix(".py")
    if as_file.is_file():
        return [as_file]
    as_pkg = src_dir.joinpath(*parts) / "__init__.py"
    if as_pkg.is_file():
        return sorted(as_pkg.parent.rglob("*.py"))
    return []


def local_imports(module_path: Path, src_dir: Path) -> list[Path]:
    """src-local files imported directly by *module_path*, sorted.

    Unfiltered on purpose: which of these a caller then wants to *exclude* is
    the caller's policy, not a fact about the import graph.
    """
    try:
        tree = parse_tree(module_path)
    except (OSError, SyntaxError):
        return []
    found: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update(resolve_local_module(alias.name, src_dir))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module_path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                prefix = base.relative_to(src_dir).parts if base != src_dir else ()
            else:
                prefix = ()
            dotted_prefix = ".".join(prefix)
            module = node.module or ""
            dotted = f"{dotted_prefix}.{module}".strip(".") if dotted_prefix else module
            if dotted:
                found.update(resolve_local_module(dotted, src_dir))
                for alias in node.names:
                    found.update(
                        resolve_local_module(f"{dotted}.{alias.name}", src_dir)
                    )
    return sorted(found)


def config_surface_paths(src_dir: Path) -> list[Path]:
    """``src/config.py`` plus the src-local modules it imports, sorted.

    Empty when there is no ``config.py`` — callers that require the config
    (rather than merely tolerating a synthetic tree without one) say so with
    their own error.
    """
    config_py = src_dir / "config.py"
    if not config_py.is_file():
        return []
    return sorted({config_py, *local_imports(config_py, src_dir)})


def _surface_trees(src_dir: Path) -> list[tuple[Path, ast.Module]]:
    trees: list[tuple[Path, ast.Module]] = []
    for path in config_surface_paths(src_dir):
        try:
            trees.append((path, parse_tree(path)))
        except (OSError, SyntaxError):
            continue
    return trees


def _class_defs(src_dir: Path) -> dict[str, ast.ClassDef]:
    """Every class defined anywhere on the surface, by name.

    Nested classes included: a decomposition may park a mixin inside a
    namespace class, and a name that resolves nowhere is indistinguishable
    from a field group that silently vanished.
    """
    found: dict[str, ast.ClassDef] = {}
    for _, tree in _surface_trees(src_dir):
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                found.setdefault(node.name, node)
    return found


def _base_names(node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def annotated_field_names(src_dir: Path, class_name: str) -> list[str]:
    """Annotated field names on *class_name*, including inherited ones, sorted.

    Follows base classes across the whole surface, so a field group that moves
    onto a mixin in a sibling module stays visible. Bases that resolve nowhere
    on the surface (``BaseModel`` and friends) contribute nothing and are not
    an error — they hold no HydraFlow dials.

    Raises when *class_name* itself is absent: that is the config having moved
    somewhere this function cannot follow, and answering "no fields" would let
    a published artifact go quietly blank.
    """
    classes = _class_defs(src_dir)
    if class_name not in classes:
        raise RuntimeError(
            f"{src_dir}: no {class_name} class found on the config surface "
            f"({', '.join(p.name for p in config_surface_paths(src_dir)) or 'no modules'})"
            " — the artifact derived from it cannot be built"
        )

    names: set[str] = set()
    seen: set[str] = set()
    pending = [class_name]
    while pending:
        current = pending.pop()
        if current in seen or current not in classes:
            continue
        seen.add(current)
        node = classes[current]
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                names.add(stmt.target.id)
        pending.extend(_base_names(node))
    return sorted(names)


def int_field_defaults(src_dir: Path) -> dict[str, int]:
    """``field_name -> int`` for every ``x: T = Field(default=<int>)`` on the surface.

    Only literal integer defaults are captured; computed and non-integer
    defaults are ignored, as the loop-interval reader has always done.
    """
    result: dict[str, int] = {}
    for _, tree in _surface_trees(src_dir):
        for node in ast.walk(tree):
            if not isinstance(node, ast.AnnAssign):
                continue
            if not isinstance(node.target, ast.Name):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            for kw in node.value.keywords:
                if (
                    kw.arg == "default"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, int)
                ):
                    result[node.target.id] = kw.value.value
                    break
    return result


def role_table(src_dir: Path) -> list[tuple[str, str, str]]:
    """``(env combo, tool field, model field)`` rows from the role registry.

    Raises when the registry is nowhere on the surface. Its sibling readers in
    the AI system inventory already fail loudly; this one used to answer ``[]``
    and render the "Model roles" section as a header with no rows.
    """
    for _, tree in _surface_trees(src_dir):
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = _assigned_value(node, ROLE_TABLE_NAME)
            if not isinstance(value, ast.List):
                continue
            rows: list[tuple[str, str, str]] = []
            for elt in value.elts:
                if isinstance(elt, ast.Tuple) and len(elt.elts) == 3:
                    parts = [
                        e.value
                        for e in elt.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                    if len(parts) == 3:
                        rows.append((parts[0], parts[1], parts[2]))
            return rows
    raise RuntimeError(
        f"{src_dir}: no {ROLE_TABLE_NAME} list found on the config surface "
        "— the AI system inventory cannot be derived"
    )


def _assigned_value(node: ast.stmt, name: str) -> ast.expr | None:
    """The value expr when *node* assigns to *name* (Assign/AnnAssign)."""
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.value if node.target.id == name else None
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == name for t in node.targets
    ):
        return node.value
    return None
