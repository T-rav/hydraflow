"""The filename globs pytest collects — read from config, spelled once.

Every tool that walks "the test suite" needs the same answer to "which files
are tests?", and the answer is not a constant: it is whatever
``[tool.pytest.ini_options] python_files`` says. When a tool hardcodes the
answer instead of reading it, the two drift the moment the config changes, and
the drift is silent in the worst direction — the tool keeps passing while
seeing less than it claims to.

That is not hypothetical here. #9801/#9872 added ``regression_*.py`` to
``python_files`` because 103 files had never been collected. Collection
widened; ``tests/architecture/test_no_ignored_active_tests.py`` kept its
hardcoded ``startswith("test")`` predicate and went on reporting zero
suppressed tests while 111 ``xfail`` markers sat in the files it could not see.

So the key path is spelled in exactly one place: here. Callers pass a repo
root and get back what pytest itself would use.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

#: pytest's own default when a project declares no ``python_files``.
#:
#: Faithfully mirrored rather than invented: a repo that sets nothing really is
#: collected this way, so a tool reading through this helper behaves like
#: pytest on any repo, not just on one that happens to configure the key.
PYTEST_DEFAULT_GLOBS: tuple[str, ...] = ("test_*.py", "*_test.py")


def collected_test_globs(repo_root: Path) -> tuple[str, ...]:
    """Filename globs pytest collects for the project rooted at *repo_root*."""
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return PYTEST_DEFAULT_GLOBS
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    patterns = (
        config.get("tool", {})
        .get("pytest", {})
        .get("ini_options", {})
        .get("python_files")
    )
    if not patterns:
        return PYTEST_DEFAULT_GLOBS
    return tuple(patterns)


def is_collected_test_file(name: str, globs: tuple[str, ...]) -> bool:
    """True when pytest would treat a file called *name* as a test module."""
    return any(fnmatch.fnmatch(name, glob) for glob in globs)
