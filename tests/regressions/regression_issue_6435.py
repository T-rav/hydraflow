"""Regression test for issue #6435 — optional-dep imports in tests stay deferred.

Bug: a test file importing an optional dependency at MODULE level fails to
collect when that package is absent, and every test in the file silently
disappears from the CI report. The convention (``docs/wiki/gotchas.md``) is to
defer such imports inside the function that needs them.

#11673 rewrote this. The original pinned three named files —
``test_hindsight.py``, ``test_memory_audit.py``,
``regressions/test_issue_6362.py`` — which were **deleted on 2026-04-22**
(#8389, Hindsight retired) *before the list was even written* on 2026-05-31.
Every parametrization hit ``pytest.skip``, and a non-strict ``xfail`` sat on
top, so the gate was 100% vacuous from birth and stayed that way for 84 days.

Its ``OPTIONAL_DEPS`` was wrong in both directions too: ``hindsight`` no longer
exists anywhere in the repo, and ``httpx`` is a CORE dependency in
``[project.dependencies]``, so importing it at module level was never a defect.
Under that set the sweep reported 24 "violations", none of them real.

The set is now DERIVED from ``pyproject.toml`` — the extras a test lane does
not necessarily install — so it cannot rot the way a hardcoded list did. The
``test`` extra is excluded because it is required to run tests at all: a test
importing ``pytest`` at module level is not taking a risk.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = _REPO_ROOT / "tests"

#: Extras that ARE installed wherever tests run, so importing from them at
#: module level carries no collection risk.
_ALWAYS_INSTALLED_EXTRAS = frozenset({"test"})


def _requirement_roots(spec: str) -> set[str]:
    """Import-name candidates for a requirement string.

    ``mkdocs-material>=9`` -> ``{"mkdocs_material", "mkdocs"}``. A distribution
    name is not always its import name, so both the normalised full name and
    the leading segment are treated as roots; over-matching here would only
    make the guard stricter, never blind.
    """
    pkg = spec.split(">")[0].split("=")[0].split("<")[0].split("[")[0].strip()
    return {pkg.replace("-", "_"), pkg.split("-")[0]}


def optional_dependency_roots() -> frozenset[str]:
    """Packages a test lane may legitimately not have installed."""
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    project = data["project"]
    core: set[str] = set()
    for spec in project.get("dependencies", []):
        core |= _requirement_roots(spec)

    optional: set[str] = set()
    for extra, specs in project.get("optional-dependencies", {}).items():
        if extra in _ALWAYS_INSTALLED_EXTRAS:
            continue
        for spec in specs:
            optional |= _requirement_roots(spec) - core
    return frozenset(optional)


def _top_level_optional_imports(
    filepath: Path, optional: frozenset[str]
) -> list[tuple[int, str]]:
    """(line, module) for each MODULE-LEVEL import of an optional dependency."""
    try:
        tree = ast.parse(filepath.read_text(errors="replace"), filename=str(filepath))
    except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
        return []

    violations: list[tuple[int, str]] = []
    for node in tree.body:  # module level only — a nested import is the fix
        if isinstance(node, ast.Import):
            violations += [
                (node.lineno, a.name)
                for a in node.names
                if a.name.split(".")[0] in optional
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in optional:
                violations.append((node.lineno, node.module))
    return violations


def _test_files() -> list[Path]:
    return sorted(
        set(TESTS_ROOT.rglob("test_*.py")) | set(TESTS_ROOT.rglob("regression_*.py"))
    )


def test_the_optional_set_is_not_empty() -> None:
    """The sweep below is vacuous if nothing is classified optional.

    This is the assertion the original lacked: its subject had evaporated and
    nothing said so.
    """
    optional = optional_dependency_roots()
    assert optional, (
        "no optional dependencies derived from pyproject.toml — the sweep "
        "below would scan every test file and can never fail. Did the extras "
        "move, or is every extra now in _ALWAYS_INSTALLED_EXTRAS?"
    )


def test_the_sweep_has_files_to_scan() -> None:
    """A discovery glob that finds nothing is a silent green."""
    assert len(_test_files()) > 100, (
        f"only {len(_test_files())} test files found under {TESTS_ROOT} — "
        "the sweep is not seeing the suite."
    )


def test_no_test_file_imports_an_optional_dependency_at_module_level() -> None:
    """Repo-wide, not a hand-listed trio that can be deleted out from under it."""
    optional = optional_dependency_roots()
    offenders: list[str] = []
    for path in _test_files():
        for lineno, module in _top_level_optional_imports(path, optional):
            rel = path.relative_to(_REPO_ROOT)
            offenders.append(f"{rel}:{lineno} imports {module!r}")

    assert not offenders, (
        "Optional dependencies must be imported INSIDE the function that needs "
        "them (docs/wiki/gotchas.md). A module-level import fails collection "
        "when the package is absent, and every test in the file vanishes from "
        "the report rather than failing.\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("dep", ["mkdocs", "ruff"])
def test_the_detector_actually_fires(tmp_path: Path, dep: str) -> None:
    """Negative control: the sweep passes today, so prove it can still fail."""
    victim = tmp_path / "test_victim.py"
    victim.write_text(f"import {dep}\n\n\ndef test_x():\n    pass\n")
    found = _top_level_optional_imports(victim, optional_dependency_roots())
    assert found == [(1, dep)], f"detector missed a module-level {dep!r} import"


def test_a_deferred_import_is_not_flagged(tmp_path: Path) -> None:
    """The convention's compliant shape must stay green."""
    ok = tmp_path / "test_ok.py"
    ok.write_text("def test_x():\n    import mkdocs\n\n    assert mkdocs\n")
    assert _top_level_optional_imports(ok, optional_dependency_roots()) == []
