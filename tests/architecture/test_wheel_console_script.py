"""Architecture guard: the wheel ships every module the console scripts need (#11580).

HydraFlow keeps ~340 flat modules directly under ``src/`` (the ``PYTHONPATH=src``
convention, see CLAUDE.md) plus a handful of sub-packages.
``[tool.setuptools.packages.find]`` discovers *packages* only, so until #11580 the
wheel built from ``pyproject.toml`` carried the sub-packages and none of the flat
modules: ``[project.scripts] hydraflow = "server:main"`` named a module that was
never installed, and the console script died at import.

The flat modules are now enumerated by ``setup.py`` (``py_modules``, a glob —
listing ~340 names by hand would put every new-module PR in merge-conflict
range). This guard keeps that shim, ``pyproject.toml`` and the source tree in
agreement without building anything:

1. every ``[project.scripts]`` target module is packaged;
2. every ``src/`` module a script transitively imports is packaged — a flat
   module through ``setup.py``, a package through ``packages.find`` — so an
   import of an excluded package (``ui``, ``templates``, ``tests``) fails here,
   not at a downstream ``pip install``;
3. no packaged module imports through the ``src.`` alias: ``src`` is the
   checkout's directory, not a package in the wheel, so ``from src.foo import
   bar`` only ever resolved because the repo root happened to be on
   ``sys.path`` (and it yields a *second* module object, #10906);
4. every non-Python file inside a packaged package (today:
   ``src/assets/model_pricing.json``, read by ``model_pricing.py`` relative to
   ``__file__``) is declared as package data.

The wheel is actually built and its console script executed in
``tests/regressions/test_issue_11580.py``.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from setuptools import find_namespace_packages

_SKIP_DIRS = {"__pycache__", "node_modules"}


@dataclass(frozen=True)
class Packaging:
    """The effective packaging config: what setuptools would put in the wheel."""

    src: Path
    flat_modules: frozenset[str]
    packages: frozenset[str]
    scripts: dict[str, str]
    package_data: dict[str, list[str]] = field(default_factory=dict)

    def top_level_is_packaged(self, name: str) -> bool:
        return name in self.flat_modules or name in self.packages


def _load_setup_shim(root: Path):
    """Import ``setup.py`` without running ``setup()`` (guarded by ``__main__``)."""
    spec = importlib.util.spec_from_file_location(
        "hydraflow_setup_shim", root / "setup.py"
    )
    assert spec is not None and spec.loader is not None, "setup.py missing"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pyproject(real_repo_root: Path) -> dict:
    return tomllib.loads((real_repo_root / "pyproject.toml").read_text("utf-8"))


@pytest.fixture
def packaging(real_repo_root: Path, pyproject: dict) -> Packaging:
    tool = pyproject["tool"]["setuptools"]
    assert tool["package-dir"] == {"": "src"}, "src-layout is load-bearing here"
    find = tool["packages"]["find"]
    src = real_repo_root / find["where"][0]
    packages = find_namespace_packages(where=str(src), exclude=find.get("exclude", []))
    shim = _load_setup_shim(real_repo_root)
    return Packaging(
        src=src,
        flat_modules=frozenset(shim.flat_modules(src)),
        packages=frozenset(p.split(".")[0] for p in packages),
        scripts=dict(pyproject["project"]["scripts"]),
        package_data={k: list(v) for k, v in tool.get("package-data", {}).items()},
    )


def _resolve(name: str, src: Path) -> Path | None:
    """Map a dotted import to the ``src/`` file defining it (None = not ours)."""
    parts = name.removeprefix("src.").split(".")
    for n in range(len(parts), 0, -1):
        base = src.joinpath(*parts[:n])
        if base.with_suffix(".py").is_file():
            return base.with_suffix(".py")
        if (base / "__init__.py").is_file():
            return base / "__init__.py"
    return None


def _import_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
            # ``from pkg import sub`` may name a submodule rather than a symbol.
            names += [f"{node.module}.{a.name}" for a in node.names]
    return names


def _top_level_unit(path: Path, src: Path) -> str:
    """``src/foo.py`` -> ``foo``; ``src/pkg/sub/mod.py`` -> ``pkg``."""
    return path.relative_to(src).parts[0].removesuffix(".py")


def transitive_units(entry: Path, src: Path) -> set[str]:
    """Top-level flat modules / packages reachable from ``entry`` by import.

    Follows lazy and ``TYPE_CHECKING`` imports too (over-approximating is the
    safe direction for "is it in the wheel?").
    """
    seen: set[Path] = set()
    units: set[str] = set()
    stack = [entry]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        units.add(_top_level_unit(path, src))
        tree = ast.parse(path.read_text("utf-8"))
        for name in _import_names(tree):
            target = _resolve(name, src)
            if target is not None and target not in seen:
                stack.append(target)
    return units


def _script_module_path(target: str, src: Path) -> Path:
    module = target.partition(":")[0]
    path = _resolve(module, src)
    assert path is not None, f"console script target {target!r} is not under src/"
    return path


def test_flat_module_shim_matches_the_source_tree(packaging: Packaging) -> None:
    """``setup.py`` enumerates exactly the top-level ``src/*.py`` modules.

    ``src/__init__.py`` is the checkout's package marker (it makes the
    ``src.`` alias importable from the repo root) — it must not become a
    top-level ``__init__`` module in the wheel.
    """
    on_disk = {p.stem for p in packaging.src.glob("*.py")} - {"__init__"}
    assert packaging.flat_modules == on_disk
    assert "server" in packaging.flat_modules
    assert "config" in packaging.flat_modules
    assert "__init__" not in packaging.flat_modules


def test_console_script_targets_are_packaged(packaging: Packaging) -> None:
    """Every ``[project.scripts]`` target resolves to a packaged module (#11580)."""
    assert packaging.scripts, "no console scripts declared"
    unpackaged = {
        name: target
        for name, target in packaging.scripts.items()
        if not packaging.top_level_is_packaged(
            _top_level_unit(_script_module_path(target, packaging.src), packaging.src)
        )
    }
    assert unpackaged == {}, (
        f"console script targets whose module the wheel would not ship: {unpackaged}"
    )


def test_console_script_import_closure_is_packaged(packaging: Packaging) -> None:
    """Every src/ unit a console script transitively imports is in the wheel."""
    for name, target in packaging.scripts.items():
        entry = _script_module_path(target, packaging.src)
        missing = sorted(
            unit
            for unit in transitive_units(entry, packaging.src)
            if not packaging.top_level_is_packaged(unit)
        )
        assert missing == [], (
            f"{name} ({target}) transitively imports src/ units the wheel does "
            f"not ship (excluded by packages.find or missing from setup.py): "
            f"{missing}"
        )


def _packaged_python_files(packaging: Packaging):
    yield from (packaging.src / f"{m}.py" for m in sorted(packaging.flat_modules))
    for pkg in sorted(packaging.packages):
        for py in sorted((packaging.src / pkg).rglob("*.py")):
            if not _SKIP_DIRS.intersection(py.parts):
                yield py


def test_packaged_modules_never_import_through_the_src_alias(
    packaging: Packaging,
) -> None:
    """``from src.foo import bar`` cannot resolve from an installed wheel.

    The alias also creates a second module object next to the bare import
    (``src.foo is not foo``), which is what #10906 banned under ``tests/``.
    """
    offenders: list[str] = []
    for py in _packaged_python_files(packaging):
        tree = ast.parse(py.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{py.relative_to(packaging.src.parent)}:{node.lineno}: "
                    f"import {a.name}"
                    for a in node.names
                    if a.name == "src" or a.name.startswith("src.")
                ]
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and (node.module == "src" or (node.module or "").startswith("src."))
            ):
                offenders.append(
                    f"{py.relative_to(packaging.src.parent)}:{node.lineno}: "
                    f"from {node.module} import ..."
                )
    assert offenders == [], (
        "Packaged modules must import bare (``from foo import ...``); ``src`` is "
        "a checkout directory, not a package in the wheel. Offenders:\n  "
        + "\n  ".join(offenders)
    )


def test_runtime_data_files_are_declared_package_data(packaging: Packaging) -> None:
    """Non-Python files under packaged packages are declared as package data.

    setuptools ships only ``*.py`` unless told otherwise; ``model_pricing.py``
    reads ``assets/model_pricing.json`` next to itself, so a wheel without it
    boots and then fails on first cost computation.
    """
    undeclared: list[str] = []
    for pkg in sorted(packaging.packages):
        patterns = packaging.package_data.get(pkg, []) + packaging.package_data.get(
            "*", []
        )
        for data in sorted((packaging.src / pkg).rglob("*")):
            if (
                not data.is_file()
                or data.suffix in {".py", ".pyc"}
                or _SKIP_DIRS.intersection(data.parts)
            ):
                continue
            rel = data.relative_to(packaging.src / pkg).as_posix()
            if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
                undeclared.append(f"{pkg}/{rel}")
    assert undeclared == [], (
        "Runtime data files under src/ packages not covered by "
        "[tool.setuptools.package-data]: " + ", ".join(undeclared)
    )
    assert "assets/model_pricing.json" not in undeclared
    assert "assets" in packaging.packages, "assets/ must be a discovered package"
