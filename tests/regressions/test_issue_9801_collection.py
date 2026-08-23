"""Regression: 72 regression_issue_*.py files were never collected (#9801/#9872).

pyproject's pytest config had no ``python_files`` override, so the default
``test_*.py`` glob silently skipped every ``regression_issue_NNNN.py`` file —
289 pinned-bug tests providing zero coverage since creation. This meta-guard
asserts every Python file in tests/regressions/ matches a configured
collection pattern, so a glob change can never silently orphan them again.

``__init__.py`` and ``_``-prefixed modules are exempt: they are shared helpers
by convention, not test files (see ``_handler_anchors.py``). The exemption is
policed by a second test here, so it cannot be used to hide a red test file.
"""

from __future__ import annotations

import ast
import fnmatch
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGRESSIONS = _REPO_ROOT / "tests" / "regressions"


def _defines_tests(path: Path) -> bool:
    """Return True if *path* defines anything pytest would treat as a test.

    Used to police the private-module exemption below: a file is only allowed
    to sit uncollected in this directory if it genuinely holds no tests.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    return any(
        (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test")
        )
        or (isinstance(node, ast.ClassDef) and node.name.startswith("Test"))
        for node in ast.walk(tree)
    )


def test_every_regression_file_matches_a_collection_pattern() -> None:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["pytest"]["ini_options"]["python_files"]

    orphans = [
        path.name
        for path in sorted(_REGRESSIONS.glob("*.py"))
        # ``__init__.py`` and ``_private.py`` modules are shared helpers, not
        # test files (e.g. ``_handler_anchors.py``, the AST anchors shared by
        # the credit-reraise regressions). The companion test below proves the
        # exemption is not a hiding place: an exempt module holding tests is
        # itself a failure.
        if path.name != "__init__.py"
        and not path.name.startswith("_")
        and not any(fnmatch.fnmatch(path.name, pat) for pat in patterns)
    ]

    assert orphans == [], (
        f"{len(orphans)} file(s) in tests/regressions/ match no pytest "
        f"python_files pattern and will silently never run: {orphans[:5]}"
    )


def test_private_helper_modules_hold_no_tests() -> None:
    """The ``_``-prefixed exemption must not become a place to hide tests.

    Without this, renaming a red regression file to ``_foo.py`` would drop it
    from collection *and* from the orphan check above — the exact silent-skip
    class #9801 was filed for.
    """
    smuggled = [
        path.name
        for path in sorted(_REGRESSIONS.glob("_*.py"))
        if path.name != "__init__.py" and _defines_tests(path)
    ]

    assert smuggled == [], (
        f"{len(smuggled)} private module(s) in tests/regressions/ define tests "
        f"but are exempt from collection, so those tests never run: {smuggled}. "
        f"Rename them to match a python_files pattern (#9801)."
    )


def test_legacy_regression_glob_is_configured() -> None:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["pytest"]["ini_options"]["python_files"]

    assert any(fnmatch.fnmatch("regression_issue_6408.py", pat) for pat in patterns)
