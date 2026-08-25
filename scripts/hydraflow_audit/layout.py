"""Layout-aware resolution of a repo's source modules (#11709).

Two ``src/`` layouts are in the wild and the audit must read both:

``flat``
    ``src/ports.py`` — HydraFlow itself, and every repo adopted from a
    pre-kernel checkout.
``packaged``
    ``src/<pkg>/ports.py`` — what ``src/onboarding/kernel_writer.py`` stamps
    for every greenfield repo (``src/{pkg}/__init__.py`` + ``pythonpath =
    ["src"]``).

A literal ``root / "src" / "ports.py"`` probe sees only the first.  On a
stamped repo the probe misses, the check returns ``FAIL: src/ports.py
missing``, and the thing the check exists to assess is never assessed — the
audit is green where it is unnecessary and silent where it is needed.  That is
#11673's family: a file path used as a proxy for a module identity, and the two
stopped agreeing.

Resolution
----------
``src_module(root, "ports")`` probes, in order:

1. ``src/ports.py``               (flat)
2. ``src/<pkg>/ports.py``         (packaged, one per root package)

and returns the first that exists.

**Flat wins when both exist.**  Two reasons, in order of weight:

* *Determinism.*  The flat path is unambiguous — it needs no discovery
  heuristic — so a repo that has it always resolves the same way regardless of
  how its ``pyproject`` is written.
* *No behaviour change on the existing corpus.*  Every flat repo the audit runs
  against today resolves exactly as it did before this module existed, which is
  the safety property that makes a 27-site conversion reviewable.

A repo holding both is mid-migration.  Resolving to the flat copy can produce a
*wrong* verdict (the flat file may be a leftover shim), but never a *silent*
one: every check reports the path it actually probed, so the answer is
diagnosable.  Silent blindness is the failure mode being fixed here; a loud,
attributable wrong answer is strictly better.

Root-package discovery
----------------------
A *root package* is a ``src/<name>/`` directory that is the repo's import root
— not merely a sub-package of a flat layout.  ``src/hydraflow_gateway/`` is a
sub-package of flat HydraFlow and must never be treated as a root, or every
missing-module message in this repo would name a path under it.

Precedence:

1. **Declared** in ``pyproject.toml`` and present on disk — setuptools
   ``package-dir`` / explicit ``packages`` list / ``packages.find.include``,
   hatch ``targets.wheel.packages``, poetry ``packages``, then ``project.name``
   normalized to an identifier (``my-app`` -> ``my_app``), which is what the
   kernel writer's ``KernelSpec.pkg`` derives when no explicit package name is
   given.  If any of these resolve, they are the answer.
2. **Filesystem fallback**, used only when nothing was declared: the
   ``src/*/`` directories holding an ``__init__.py``, but *only* when ``src/``
   holds no top-level ``*.py`` modules.  A top-level module means the repo's
   import root is ``src/`` itself, so its package directories are sub-packages,
   not roots.
3. Otherwise **no root package** — resolution is flat-only, exactly as before.

``[project.scripts]`` is deliberately *not* a discovery source.  HydraFlow's
own ``hydraflow-gateway = "hydraflow_gateway.__main__:main"`` would nominate a
sub-package of a flat repo as its root.

Multiple candidates are kept, in declared order then sorted, and probed in
turn: the first package that actually holds the module wins.  Ambiguity is
resolved by what is on disk rather than by refusing to look.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "SOURCE_DIR_NAME",
    "root_packages",
    "src_candidates",
    "src_dir",
    "src_module",
    "src_root",
]

#: The one spelling of the source directory in the whole audit package.
#:
#: Every other module reaches the source tree through ``ctx.src_root`` /
#: ``ctx.src_module`` / ``ctx.src_dir``, or through this constant. That is not
#: style: it is what makes the #11709 ratchet unevadable. A gate that matches
#: AST SHAPES has to enumerate them, and every shape it has not thought of
#: (``PurePath("src")``, ``_SRC = "src"``, ``f"src/{name}.py"``) walks straight
#: through — the same enumeration drift this package was fixed for. A gate that
#: matches the LITERAL only has to know one thing, and every spelling of the
#: hazard must contain it.
SOURCE_DIR_NAME = "src"

#: Directories under ``src/`` that are never a package.
_NOT_A_PACKAGE = frozenset({"__pycache__", "node_modules"})

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def src_root(root: Path) -> Path:
    """The source directory itself — the root of a recursive scan.

    Correct for both layouts without any package knowledge: walking ``src/``
    with ``rglob`` reaches ``src/<pkg>/**`` too. That is why P9.2 kept working
    while its sibling P9.1 went blind, and it is the reason this is a distinct
    call rather than a special case of :func:`src_dir`.
    """
    return root / SOURCE_DIR_NAME


def root_packages(root: Path) -> tuple[str, ...]:
    """Root package names under ``src/``, most-authoritative first.

    Empty for a flat repo (including a flat repo that happens to contain
    sub-packages, which is HydraFlow).
    """
    src = src_root(root)
    if not src.is_dir():
        return ()
    declared = tuple(name for name in _declared_packages(root) if (src / name).is_dir())
    if declared:
        return declared
    if _has_top_level_modules(src):
        # ``src/`` is itself the import root; its directories are sub-packages.
        return ()
    return _package_dirs(src)


def src_candidates(
    root: Path, parts: tuple[str, ...], packages: tuple[str, ...] | None = None
) -> tuple[Path, ...]:
    """Every path ``parts`` could live at, flat first then one per root package."""
    flat, packaged = _split_candidates(root, parts, packages)
    return (flat, *packaged)


def src_module(root: Path, name: str, packages: tuple[str, ...] | None = None) -> Path:
    """Resolve source module ``name`` (no ``.py``) across both layouts.

    Returns the first candidate that is a file.  When none exist, returns the
    candidate the repo's own layout implies — the packaged path on a packaged
    repo — so the caller's ``... missing`` message names a path the repo would
    actually use.
    """
    return _resolve(root, (f"{name}.py",), packages, Path.is_file)


def src_dir(root: Path, *parts: str, packages: tuple[str, ...] | None = None) -> Path:
    """Resolve a source *directory* (``domain``, ``ui``, ``mockworld/fakes``)."""
    return _resolve(root, parts, packages, Path.is_dir)


# ---------------------------------------------------------------------------
# Internals.
# ---------------------------------------------------------------------------


def _split_candidates(
    root: Path, parts: tuple[str, ...], packages: tuple[str, ...] | None
) -> tuple[Path, list[Path]]:
    src = src_root(root)
    pkgs = root_packages(root) if packages is None else packages
    return src.joinpath(*parts), [src.joinpath(pkg, *parts) for pkg in pkgs]


def _resolve(
    root: Path,
    parts: tuple[str, ...],
    packages: tuple[str, ...] | None,
    predicate: Callable[[Path], bool],
) -> Path:
    flat, packaged = _split_candidates(root, parts, packages)
    for candidate in (flat, *packaged):
        if predicate(candidate):
            return candidate
    # Nothing on disk. Prefer the primary packaged spelling so the failure
    # message names the path this repo's layout implies, not a flat path that
    # a packaged repo would never use.
    return packaged[0] if packaged else flat


def _package_dirs(src: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            child.name
            for child in src.iterdir()
            if child.is_dir()
            and not child.name.startswith(".")
            and child.name not in _NOT_A_PACKAGE
            and (child / "__init__.py").is_file()
        )
    )


def _has_top_level_modules(src: Path) -> bool:
    return any(
        child.is_file() and child.suffix == ".py" and child.name != "__init__.py"
        for child in src.iterdir()
    )


def _load_pyproject(root: Path) -> dict:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _declared_packages(root: Path) -> tuple[str, ...]:
    """Package names a build backend declares, in precedence order."""
    data = _load_pyproject(root)
    if not data:
        return ()
    tool = data.get("tool")
    tool = tool if isinstance(tool, dict) else {}
    names: list[str] = []
    for name in (
        *_setuptools_names(tool),
        *_hatch_names(tool),
        *_poetry_names(tool),
        *_project_name(data),
    ):
        if _IDENTIFIER_RE.match(name) and name not in names:
            names.append(name)
    return tuple(names)


def _table(parent: dict, *keys: str) -> dict:
    node: object = parent
    for key in keys:
        if not isinstance(node, dict):
            return {}
        node = node.get(key)
    return node if isinstance(node, dict) else {}


def _strings(value: object) -> list[str]:
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


def _setuptools_names(tool: dict) -> list[str]:
    setuptools = _table(tool, "setuptools")
    names: list[str] = []
    # ``package-dir = {"pkg" = "src/pkg"}`` names a package; the common
    # ``{"" = "src"}`` form only says *where* and contributes nothing.
    for key in _table(setuptools, "package-dir"):
        if isinstance(key, str) and key:
            names.append(key.split(".", 1)[0])
    packages = setuptools.get("packages")
    for entry in _strings(packages):
        names.append(entry.split(".", 1)[0])
    find = packages if isinstance(packages, dict) else setuptools
    for entry in _strings(_table(find, "find").get("include")):
        stem = entry.rstrip("*").rstrip(".")
        if stem and "." not in stem:
            names.append(stem)
    return names


def _hatch_names(tool: dict) -> list[str]:
    entries = _strings(
        _table(tool, "hatch", "build", "targets", "wheel").get("packages")
    )
    return [Path(entry).name for entry in entries]


def _poetry_names(tool: dict) -> list[str]:
    packages = _table(tool, "poetry").get("packages")
    if not isinstance(packages, list):
        return []
    names: list[str] = []
    for entry in packages:
        include = entry.get("include") if isinstance(entry, dict) else None
        if isinstance(include, str) and include:
            names.append(include.split(".", 1)[0].rstrip("*"))
    return names


def _project_name(data: dict) -> list[str]:
    """``project.name`` as an import identifier — ``my-app`` -> ``my_app``.

    Mirrors ``KernelSpec.pkg``, which derives the stamped package name this way
    whenever no explicit ``package_name`` is given.
    """
    name = _table(data, "project").get("name")
    if not isinstance(name, str):
        return []
    return [name.strip().lower().replace("-", "_").replace(".", "_")]
