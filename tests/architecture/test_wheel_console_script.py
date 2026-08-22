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
4. every non-Python file inside a packaged package (``src/assets/*.json`` read
   by ``model_pricing.py``; the ``src/hydraflow_resources/`` trees read through
   ``package_resources``) is declared as package data;
5. no packaged module walks up from ``__file__`` to guess a repo root — the
   #11589 class. ``Path(__file__).resolve().parent.parent`` names the checkout
   root from ``<repo>/src/mod.py`` and ``lib/python3.11/`` from
   ``site-packages/mod.py``, so it silently resolves to a directory that does
   not exist in a wheel install. ``package_resources`` answers both questions
   the idiom conflated, and this guard keeps the idiom from growing back.

The wheel is actually built and its console script executed in
``tests/regressions/test_issue_11580.py``; a migrated resource is resolved
from an installed wheel in ``tests/regressions/test_issue_11589.py``.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from setuptools import find_namespace_packages

_SKIP_DIRS = {"__pycache__", "node_modules"}

#: ``__file__`` walked up past its own directory — ``.parent.parent``,
#: ``.parents[n]``, or nested ``dirname()``. A single ``.parent`` /
#: ``dirname()`` (``model_pricing.py``'s ``Path(__file__).parent / "assets"``)
#: is package-relative and correct, so only two-or-more levels are flagged.
_WALK_UP = re.compile(
    r"__file__.*?(?:\.parent\.parent|\.parents\s*\[)"
    r"|dirname\([^()]*dirname\(.*?__file__"
)

#: Modules allowed to walk up from ``__file__``. ``package_resources`` is the
#: one place the question is answered — grandfather nothing else: every site
#: the #11589 sweep found was migrated, so this list must stay a singleton
#: unless a new module has a reason no reviewer can refute.
_WALK_UP_ALLOWED = frozenset({"package_resources.py"})


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


def test_every_declared_resource_tree_is_packaged(packaging: Packaging) -> None:
    """``package_resources.RESOURCE_TREES`` and the wheel cannot disagree.

    The trees are runtime inputs (auto-agent prompts, the dashboard's fallback
    template + JS): code that names one and packaging that omits it is the
    #11589 failure in a new shape — importable wheel, unusable server.
    """
    from package_resources import RESOURCE_PACKAGE, RESOURCE_TREES

    resources = packaging.src / RESOURCE_PACKAGE
    missing = sorted(t for t in RESOURCE_TREES if not (resources / t).is_dir())
    assert missing == [], (
        f"package_resources.RESOURCE_TREES names trees that do not exist under "
        f"src/{RESOURCE_PACKAGE}/: {missing}"
    )
    assert RESOURCE_PACKAGE in packaging.packages
    assert packaging.package_data.get(RESOURCE_PACKAGE), (
        f"src/{RESOURCE_PACKAGE}/ holds no .py files, so setuptools ships "
        "nothing from it without a [tool.setuptools.package-data] entry"
    )


def test_no_resource_tree_ships_without_being_named(packaging: Packaging) -> None:
    """A tree under ``src/hydraflow_resources/`` that code cannot ask for is dead weight."""
    from package_resources import RESOURCE_PACKAGE, RESOURCE_TREES

    resources = packaging.src / RESOURCE_PACKAGE
    on_disk = sorted(p.name for p in resources.iterdir() if p.is_dir())
    assert on_disk == sorted(RESOURCE_TREES), (
        f"src/{RESOURCE_PACKAGE}/ and package_resources.RESOURCE_TREES disagree: "
        f"on disk {on_disk}, declared {sorted(RESOURCE_TREES)}"
    )


def test_resource_trees_are_one_package_not_many(
    packaging: Packaging, pyproject: dict
) -> None:
    """The nested trees must not be discovered as their own packages.

    ``package-data`` belongs to the package that owns the file. If
    ``hydraflow_resources.prompts.auto_agent`` were discovered as a package,
    the parent's recursive glob would stop covering it and a newly added
    sub-directory would ship empty.
    """
    from package_resources import RESOURCE_PACKAGE

    exclude = pyproject["tool"]["setuptools"]["packages"]["find"]["exclude"]
    assert f"{RESOURCE_PACKAGE}.*" in exclude
    found = find_namespace_packages(where=str(packaging.src), exclude=exclude)
    nested = sorted(p for p in found if p.startswith(f"{RESOURCE_PACKAGE}."))
    assert nested == [], f"resource sub-trees discovered as packages: {nested}"


def _walk_up_sites(path: Path, src: Path) -> list[str]:
    """``file:line`` for each expression in *path* that walks up from ``__file__``."""
    tree = ast.parse(path.read_text("utf-8"))
    lines = {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute | ast.Subscript | ast.Call)
        and _WALK_UP.search(ast.unparse(node))
    }
    return [f"{path.relative_to(src.parent)}:{line}" for line in sorted(lines)]


def test_packaged_modules_never_derive_a_root_from_dunder_file(
    packaging: Packaging,
) -> None:
    """No module reinvents "the repo root" from ``__file__`` (#11589).

    ``Path(__file__).resolve().parent.parent`` means ``<repo>`` from
    ``<repo>/src/mod.py`` and ``lib/python3.11/`` from ``site-packages/mod.py``,
    so every resource read through it was a silent wrong-directory lookup once
    the wheel became installable (#11580). Use ``package_resources``:
    ``resource_dir``/``resource_path`` for data that ships with HydraFlow,
    ``checkout_root``/``checkout_path`` for development-only inputs, and
    ``HydraFlowConfig.repo_root`` for the repository being operated on.
    """
    offenders: list[str] = []
    for py in _packaged_python_files(packaging):
        if py.name in _WALK_UP_ALLOWED and py.parent == packaging.src:
            continue
        offenders += _walk_up_sites(py, packaging.src)
    assert offenders == [], (
        "Packaged modules deriving a root by walking up from __file__ — this "
        "resolves inside site-packages in a wheel install (#11589). Route the "
        "lookup through src/package_resources.py instead. Offenders:\n  "
        + "\n  ".join(offenders)
    )
