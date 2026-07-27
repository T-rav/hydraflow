"""ADR-0065 enforcement: CodeGroomingLoop is removed and stays removed.

ADR-0065 (Remove CodeGroomingLoop) decides the loop is deleted along with its
state slice and settings model, keeping only the ``/hf.audit-code`` skill as a
manual path (Decision §1, §2, §4). The decision's own enforcement note asks
that ``grep -rn 'code_grooming|CodeGrooming' src/ tests/`` return "no live
references" — the word *live* is load-bearing: incidental mentions in comments
and docstrings (this ADR is cited by name in a few comments) are allowed, but
no executable code may define, import, or reference the removed loop.

These asserting tests encode that invariant. The "no live references" scan
walks the AST for *identifiers* and *imports* only, so prose in comments and
docstring/string literals is correctly ignored while any real code reference
(a class/function definition, a name/attribute use, or an import of the
``code_grooming_loop`` module) fails the check.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_CAMEL = "CodeGrooming"  # matches CodeGroomingLoop, CodeGroomingSettings, ...
_MODULE = "code_grooming"  # matches the code_grooming_loop module family


def _live_references(base: Path) -> list[str]:
    """Return ``path::symbol`` for every *executable* reference to the removed
    loop under *base* — AST identifiers/imports only, never comments/strings."""
    offenders: list[str] = []
    for path in base.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = path.name
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                and _CAMEL in node.name
            ):
                offenders.append(f"{rel}::def {node.name}")
            elif isinstance(node, ast.Name) and _CAMEL in node.id:
                offenders.append(f"{rel}::name {node.id}")
            elif isinstance(node, ast.Attribute) and _CAMEL in node.attr:
                offenders.append(f"{rel}::attr {node.attr}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (_MODULE in node.module)
            ):
                offenders.append(f"{rel}::from {node.module}")
            elif isinstance(node, ast.Import):
                offenders.extend(
                    f"{rel}::import {alias.name}"
                    for alias in node.names
                    if _MODULE in alias.name
                )
    return offenders


def test_code_grooming_loop_module_and_state_slice_are_deleted(
    real_repo_root: Path,
) -> None:
    """ADR-0065 §1, §4: the loop module and its state slice no longer exist,
    and the module is not importable (no shim / re-export)."""
    assert not (real_repo_root / "src" / "code_grooming_loop.py").exists()
    assert not (real_repo_root / "src" / "state" / "_code_grooming.py").exists()
    assert importlib.util.find_spec("code_grooming_loop") is None


def test_no_live_code_grooming_references_in_src_or_tests(
    real_repo_root: Path,
) -> None:
    """ADR-0065 §2: no executable code under src/ or tests/ defines, imports,
    or references the removed loop (comments and docstrings are exempt)."""
    offenders = _live_references(real_repo_root / "src")
    offenders += _live_references(real_repo_root / "tests")
    assert not offenders, (
        "live CodeGroomingLoop references remain (ADR-0065 requires the loop be "
        f"fully removed): {sorted(offenders)}"
    )
