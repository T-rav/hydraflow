"""ADR-0027 enforcement: no dead merge-artifact duplicate model classes.

ADR-0027 (Duplicate Class Definitions — Merge-Artifact Pattern) Rule 1 requires
every model class (Pydantic ``BaseModel`` subclass, ``@dataclass``, or
``TypedDict``) to have exactly one definition across ``src/``. Rule 3 names the
concrete symptom: when a duplicate slips through, "the `models.py` copy tends
to become dead code: nothing imports it" — the module-level copy is never
referenced by any other file, and never used within its own file either.

A blanket "no duplicate class names" check is not viable here (see
``docs/standards/adr_enforcement/exemptions.md``'s former ADR-0027 entry): the
tree legitimately carries same-named classes in unrelated namespaces (e.g.
per-domain ``GateResult``/``CheckResult``), each actively used where it's
defined. So this test targets the actual bug Rule 3 describes, not mere name
collision: among classes that share a name across 2+ ``src/`` files, flag only
a definition that is *unreferenced* — no other file imports it from its
module, AND it is never used (as a type, call, or field annotation) anywhere
within its own defining file either. That is the dead merge-artifact copy;
a duplicate whose every definition is genuinely used somewhere is Rule 4's
"intentional and documented" case and passes untouched.
"""

from __future__ import annotations

import ast
from pathlib import Path

_EXCLUDED_BASES = frozenset(
    {
        "Protocol",
        "ABC",
        "Enum",
        "IntEnum",
        "StrEnum",
        "Flag",
        "IntFlag",
        "Exception",
        "BaseException",
    }
)


def _base_names(cls: ast.ClassDef) -> list[str]:
    names = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _decorator_names(cls: ast.ClassDef) -> list[str]:
    names = []
    for dec in cls.decorator_list:
        if isinstance(dec, ast.Name):
            names.append(dec.id)
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            names.append(dec.func.id)
        elif isinstance(dec, ast.Attribute):
            names.append(dec.attr)
    return names


def _is_model_class(cls: ast.ClassDef) -> bool:
    """True for a Pydantic ``BaseModel``, ``@dataclass``, or ``TypedDict`` —
    ADR-0027 Rule 1's scope — excluding Rule 4's Protocol/ABC/Enum/Exception
    interfaces, which are not data models."""
    bases = _base_names(cls)
    if any(b in _EXCLUDED_BASES for b in bases):
        return False
    return (
        "dataclass" in _decorator_names(cls)
        or "BaseModel" in bases
        or "TypedDict" in bases
    )


def _module_name(path: Path, src_root: Path) -> str:
    parts = list(path.relative_to(src_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _parse_all(src_root: Path) -> dict[Path, ast.Module]:
    """Parse every ``src/`` file exactly once — shared by the class-definition
    scan and the import-index build so neither re-parses the tree."""
    trees: dict[Path, ast.Module] = {}
    for path in _all_source_files(src_root):
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
    return trees


def _model_class_definitions(trees: dict[Path, ast.Module]) -> dict[str, list[Path]]:
    """Map each model-class name to every ``src/`` file that defines it."""
    by_name: dict[str, list[Path]] = {}
    for path in sorted(trees):
        for node in ast.walk(trees[path]):
            if isinstance(node, ast.ClassDef) and _is_model_class(node):
                by_name.setdefault(node.name, []).append(path)
    return by_name


def _package_of(path: Path, src_root: Path) -> str:
    """Dotted package a relative import inside *path* resolves against —
    *path* itself if it's an ``__init__.py`` (a package), else its parent
    package, mirroring Python's ``__package__`` semantics."""
    dotted = _module_name(path, src_root)
    if path.name == "__init__.py":
        return dotted
    return dotted.rsplit(".", 1)[0] if "." in dotted else ""


def _resolve_relative_module(path: Path, src_root: Path, node: ast.ImportFrom) -> str:
    """Absolute dotted module a ``from .foo import Bar`` in *path* targets."""
    package = _package_of(path, src_root)
    bits = package.rsplit(".", node.level - 1) if package else [""]
    base = bits[0]
    return f"{base}.{node.module}" if node.module else base


def _build_import_index(
    src_root: Path, trees: dict[Path, ast.Module]
) -> dict[tuple[str, str], set[Path]]:
    """Map ``(imported_name, resolved_source_module)`` to every file that
    imports it, built with a single ``ast.walk`` per file. Precomputing this
    index avoids re-walking every file's AST once per duplicate definition —
    an O(duplicates x files) cost that made this check slow enough to eat a
    large share of the test-duration-ratchet budget."""
    index: dict[tuple[str, str], set[Path]] = {}
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level == 0:
                module = node.module or ""
                if module.startswith("src."):
                    module = module[len("src.") :]
            else:
                module = _resolve_relative_module(path, src_root, node)
            for alias in node.names:
                index.setdefault((alias.name, module), set()).add(path)
    return index


def _referenced_within_file(tree: ast.Module, name: str) -> bool:
    """True if *name* is used anywhere in *tree* as a real reference (a type
    annotation, call, base class, etc.) — an ``ast.Name`` load, or a quoted
    forward-reference string literal that is exactly the class name (e.g.
    ``x: "Foo"``, or the ``"Foo"`` inside ``Optional["Foo"]``). Unlike the
    sibling ADR-0023 check (scoped to test-function bodies, where a stray
    string constant is almost always a ``locals()``/``globals()`` lookup), this
    check scans whole ``src/`` files, where prose — docstrings, log messages,
    error text — routinely *mentions* a class name without using it; matching
    by substring there would silently treat "Deprecated: use Foo instead" as a
    reference and hide a genuinely dead duplicate. Exact string equality still
    catches the forward-reference case while excluding prose. A class's own
    ``ClassDef`` header is not an ``ast.Name`` node, so this never counts a
    definition as a reference to itself."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value == name
        ):
            return True
    return False


def _dead_duplicate_definitions(src_root: Path) -> list[str]:
    """Return ``module.py::ClassName`` for every duplicate-named model class
    definition that no other file imports and that is never referenced within
    its own defining file — the ADR-0027 Rule 3 dead merge-artifact copy."""
    trees = _parse_all(src_root)
    by_name = _model_class_definitions(trees)
    import_index = _build_import_index(src_root, trees)

    offenders: list[str] = []
    for name, paths in sorted(by_name.items()):
        if len(paths) < 2:
            continue
        for defpath in paths:
            module = _module_name(defpath, src_root)
            importers = import_index.get((name, module), set()) - {defpath}
            if importers:
                continue
            if _referenced_within_file(trees[defpath], name):
                continue
            offenders.append(f"{defpath.relative_to(src_root.parent)}::{name}")
    return offenders


def _all_source_files(src_root: Path) -> list[Path]:
    return sorted(src_root.rglob("*.py"))


def test_no_dead_duplicate_model_class_definitions(real_repo_root: Path) -> None:
    """ADR-0027 Rule 3: a duplicate-named model class definition must not be a
    dead merge-artifact copy — every definition must be imported by another
    module or referenced within its own file."""
    offenders = _dead_duplicate_definitions(real_repo_root / "src")
    assert not offenders, (
        "dead merge-artifact duplicate model class definition(s) found "
        "(ADR-0027 Rule 3: the module.py copy is never imported and never "
        f"used): {offenders}. Delete the dead copy per Rule 3, or if both "
        "definitions are genuinely used, this is a false positive — file a "
        "hydraflow-find issue."
    )


def test_dead_duplicate_definition_is_detected_in_synthetic_tree(
    fixture_src_tree,
) -> None:
    """Positive control: a genuinely dead duplicate — one copy orphaned, the
    other imported and used — must be flagged. Proves the detector can
    actually fail rather than only ever passing on the live tree."""
    root = fixture_src_tree(
        {
            "src/models.py": """
                from pydantic import BaseModel

                class Widget(BaseModel):
                    name: str
            """,
            "src/feature.py": """
                from pydantic import BaseModel

                class Widget(BaseModel):
                    label: str

                def build() -> Widget:
                    return Widget(label="x")
            """,
        }
    )
    assert _dead_duplicate_definitions(root / "src") == ["src/models.py::Widget"]


def test_duplicate_definition_both_used_is_not_flagged(fixture_src_tree) -> None:
    """Negative control: same-named classes that are each independently used
    (Rule 4's documented-intentional-duplicate case) must not be flagged."""
    root = fixture_src_tree(
        {
            "src/models.py": """
                from pydantic import BaseModel

                class Widget(BaseModel):
                    name: str

                def make() -> Widget:
                    return Widget(name="x")
            """,
            "src/feature.py": """
                from pydantic import BaseModel

                class Widget(BaseModel):
                    label: str

                def build() -> Widget:
                    return Widget(label="x")
            """,
        }
    )
    assert _dead_duplicate_definitions(root / "src") == []


def test_duplicate_referenced_only_via_quoted_annotation_is_not_flagged(
    fixture_src_tree,
) -> None:
    """A duplicate referenced only through a quoted forward-reference
    annotation (``w: "Widget"``) counts as used — not every real reference is
    an ``ast.Name`` load."""
    root = fixture_src_tree(
        {
            "src/models.py": """
                from pydantic import BaseModel

                class Widget(BaseModel):
                    name: str

                def make(w: "Widget") -> None:
                    pass
            """,
            "src/feature.py": """
                from pydantic import BaseModel

                class Widget(BaseModel):
                    label: str

                def build() -> Widget:
                    return Widget(label="x")
            """,
        }
    )
    assert _dead_duplicate_definitions(root / "src") == []


def test_dead_duplicate_mentioned_only_in_own_docstring_is_still_flagged(
    fixture_src_tree,
) -> None:
    """A dead copy's docstring mentioning its own class name (e.g. "Deprecated:
    use feature.Widget instead") must not count as a reference — only an exact
    string match (a forward-reference annotation) does. Guards against a
    substring match silently un-flagging the exact merge-artifact case this
    check exists to catch."""
    root = fixture_src_tree(
        {
            "src/models.py": '''
                from pydantic import BaseModel

                class Widget(BaseModel):
                    """Deprecated shim; superseded by feature.Widget."""

                    name: str
            ''',
            "src/feature.py": """
                from pydantic import BaseModel

                class Widget(BaseModel):
                    label: str

                def build() -> Widget:
                    return Widget(label="x")
            """,
        }
    )
    assert _dead_duplicate_definitions(root / "src") == ["src/models.py::Widget"]
