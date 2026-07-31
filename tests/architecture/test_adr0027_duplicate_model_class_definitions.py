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


def _model_class_definitions(src_root: Path) -> dict[str, list[Path]]:
    """Map each model-class name to every ``src/`` file that defines it."""
    by_name: dict[str, list[Path]] = {}
    for path in sorted(src_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _is_model_class(node):
                by_name.setdefault(node.name, []).append(path)
    return by_name


def _imports_name_from_module(tree: ast.Module, module: str, name: str) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module in (module, f"src.{module}")
        and any(alias.name == name for alias in node.names)
        for node in ast.walk(tree)
    )


def _referenced_within_file(tree: ast.Module, name: str) -> bool:
    """True if *name* is used anywhere in *tree* as a real reference (a type
    annotation, call, base class, etc.) — an ``ast.Name`` load. A class's own
    ``ClassDef`` header is not an ``ast.Name`` node, so this never counts a
    definition as a reference to itself."""
    return any(
        isinstance(node, ast.Name) and node.id == name for node in ast.walk(tree)
    )


def _dead_duplicate_definitions(src_root: Path) -> list[str]:
    """Return ``module.py::ClassName`` for every duplicate-named model class
    definition that no other file imports and that is never referenced within
    its own defining file — the ADR-0027 Rule 3 dead merge-artifact copy."""
    by_name = _model_class_definitions(src_root)
    trees: dict[Path, ast.Module] = {}

    def _tree(path: Path) -> ast.Module:
        if path not in trees:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"))
        return trees[path]

    offenders: list[str] = []
    for name, paths in sorted(by_name.items()):
        if len(paths) < 2:
            continue
        for defpath in paths:
            module = _module_name(defpath, src_root)
            imported_elsewhere = any(
                other != defpath
                and _imports_name_from_module(_tree(other), module, name)
                for other in _all_source_files(src_root)
            )
            if imported_elsewhere:
                continue
            if _referenced_within_file(_tree(defpath), name):
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
