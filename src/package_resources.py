"""One resolver for HydraFlow's non-Python resources (#11589).

Eight modules used to spell the repo root ``Path(__file__).resolve().parent.parent``
and read ``prompts/``, ``templates/``, ``static/`` or ``docs/standards/`` from
it. That expression means two different things depending on where the module
sits: ``<repo>`` from ``<repo>/src/mod.py``, and ``lib/python3.11/`` from
``site-packages/mod.py``. So after #11580 made the wheel importable, every one
of those reads resolved to a directory that does not exist — silently, with a
``FileNotFoundError`` naming a path nobody would recognise.

The idiom conflated two genuinely different questions, which is why one
expression could not answer either well:

*Where is a resource that ships with HydraFlow?*
    ``prompts/``, ``templates/`` and ``static/`` are runtime inputs; the code
    is useless without them. They live under ``src/hydraflow_resources/`` and
    are declared package data, exactly like ``src/assets/model_pricing.json``
    (``pyproject.toml`` ``[tool.setuptools.package-data]``), so
    :func:`package_root` — ``<repo>/src`` in a checkout, ``site-packages`` from
    a wheel — locates them in both layouts with one expression. Use
    :func:`resource_dir` / :func:`resource_path`.

*Where is the HydraFlow source checkout?*
    ``docs/standards/``, ``scripts/audit_prompts.py`` and the git metadata the
    repro manifest hashes are development artefacts that are deliberately
    **not** in the wheel. Code that wants them wants a checkout, and from an
    installed wheel there may not be one. Use :func:`checkout_root` (``None``
    when there is no checkout) or :func:`checkout_path` (raises).

Neither of these is "the repository HydraFlow is operating on" — that is
``HydraFlowConfig.repo_root`` and it must never be resolved from ``__file__``.

Both resolutions take an explicit operator override first
(``HYDRAFLOW_RESOURCE_ROOT`` / ``HYDRAFLOW_ROOT``), and neither ever returns a
path that does not exist: the failure is a :class:`ResourceNotFoundError` that
names every candidate it tried. ``tests/architecture/test_wheel_console_script.py``
keeps the old idiom from growing back.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

__all__ = [
    "CHECKOUT_ROOT_ENV",
    "RESOURCE_PACKAGE",
    "RESOURCE_ROOT_ENV",
    "RESOURCE_TREES",
    "ResourceNotFoundError",
    "checkout_path",
    "checkout_root",
    "find_checkout_root",
    "package_root",
    "resource_dir",
    "resource_path",
]

#: Operator override for the shipped resource trees (a directory holding
#: ``prompts/``, ``templates/``, ``static/``). Set it to a checkout's
#: ``src/hydraflow_resources`` to run a wheel against edited prompts.
RESOURCE_ROOT_ENV = "HYDRAFLOW_RESOURCE_ROOT"

#: Operator override for the HydraFlow source checkout root.
CHECKOUT_ROOT_ENV = "HYDRAFLOW_ROOT"

#: Package directory (under :func:`package_root`) holding the resource trees.
RESOURCE_PACKAGE = "hydraflow_resources"

#: The resource trees HydraFlow ships. Named rather than free-form so a typo
#: fails with "unknown resource" instead of "directory not found", and so
#: packaging and code cannot disagree about what must be in the wheel —
#: ``tests/architecture/test_wheel_console_script.py`` binds this tuple to the
#: on-disk trees and to ``[tool.setuptools.package-data]``.
RESOURCE_TREES: tuple[str, ...] = ("prompts", "static", "templates")

#: A directory is a HydraFlow checkout when it holds ``src/<this module>``.
#: Deliberately not ``pyproject.toml``: the agent image copies ``src/`` and
#: ``tests/`` to ``/opt/hydraflow`` without it (Dockerfile.agent), and that
#: layout is a checkout for every purpose this module serves.
_CHECKOUT_MARKER = ("src", "package_resources.py")


class ResourceNotFoundError(RuntimeError):
    """A HydraFlow resource could not be located in any supported layout."""


def package_root() -> Path:
    """Directory the HydraFlow modules are installed in.

    ``<repo>/src`` under the ``PYTHONPATH=src`` convention, ``site-packages``
    from an installed wheel. Package data sits beside the modules in both.
    """
    return Path(__file__).resolve().parent


def _override(env: str) -> Path | None:
    """The operator's override for *env*, or ``None`` when unset/blank."""
    raw = os.environ.get(env, "").strip()
    return Path(raw).expanduser() if raw else None


def find_checkout_root(start: Path) -> Path | None:
    """Nearest ancestor of *start* (inclusive) that is a HydraFlow checkout."""
    for candidate in (start, *start.parents):
        if candidate.joinpath(*_CHECKOUT_MARKER).is_file():
            return candidate
    return None


@cache
def _installed_checkout_root() -> Path | None:
    """:func:`find_checkout_root` from this module's own location.

    Cached: the installed layout cannot change while the process runs, and
    this is called from config properties on hot paths.
    """
    return find_checkout_root(package_root())


def checkout_root() -> Path | None:
    """Root of the HydraFlow *source checkout*, or ``None`` from a wheel.

    Callers that cannot proceed without one should use :func:`checkout_path`,
    which raises with the reason instead of degrading.

    Raises:
        ResourceNotFoundError: ``HYDRAFLOW_ROOT`` is set to a missing directory.
    """
    override = _override(CHECKOUT_ROOT_ENV)
    if override is not None:
        if not override.is_dir():
            raise ResourceNotFoundError(
                f"{CHECKOUT_ROOT_ENV}={override} is not a directory; unset it or "
                "point it at a HydraFlow checkout."
            )
        return override
    return _installed_checkout_root()


def checkout_path(*parts: str) -> Path:
    """Path to *parts* inside the HydraFlow checkout; raises if unavailable.

    For development-only inputs (``docs/standards/``, ``scripts/``, git
    metadata) that are deliberately absent from the wheel. Called with no
    parts it returns the checkout root itself, for callers that need a clone
    to exist at all.

    Raises:
        ResourceNotFoundError: there is no checkout, or the path is missing.
    """
    joined = Path(*parts).as_posix() if parts else "the HydraFlow checkout"
    root = checkout_root()
    if root is None:
        raise ResourceNotFoundError(
            f"{joined} needs a HydraFlow source checkout, and this HydraFlow is "
            f"running from {package_root()} (no checkout above it). Run from a "
            f"clone, or set {CHECKOUT_ROOT_ENV} to one."
        )
    resolved = root.joinpath(*parts)
    if not resolved.exists():
        raise ResourceNotFoundError(
            f"{joined} is missing from the HydraFlow checkout at {root}."
        )
    return resolved


def _resource_candidates(tree: str) -> list[tuple[str, Path]]:
    """(label, path) candidates for *tree*, in precedence order."""
    override = _override(RESOURCE_ROOT_ENV)
    if override is not None:
        # An explicit override is the whole answer: falling through to the
        # packaged copy would quietly ignore what the operator asked for.
        return [(f"{RESOURCE_ROOT_ENV}={override}", override / tree)]
    candidates = [("packaged", package_root() / RESOURCE_PACKAGE / tree)]
    checkout = checkout_root()
    if checkout is not None:
        candidates.append(
            ("checkout", checkout / "src" / RESOURCE_PACKAGE / tree),
        )
    return candidates


def resource_dir(tree: str) -> Path:
    """Directory of the shipped resource *tree* (``"prompts"``, ...).

    Precedence: ``HYDRAFLOW_RESOURCE_ROOT`` override, the tree packaged beside
    the installed modules, then the surrounding checkout (which matters only
    when the package data failed to install).

    Raises:
        ResourceNotFoundError: unknown tree name, or no candidate exists.
    """
    if tree not in RESOURCE_TREES:
        raise ResourceNotFoundError(
            f"unknown HydraFlow resource tree {tree!r}; "
            f"known trees: {', '.join(RESOURCE_TREES)}."
        )
    candidates = _resource_candidates(tree)
    for _, path in candidates:
        if path.is_dir():
            return path
    tried = "; ".join(f"{label}: {path}" for label, path in candidates)
    raise ResourceNotFoundError(
        f"HydraFlow resource tree {tree!r} not found. Tried {tried}. It ships as "
        f"package data (src/{RESOURCE_PACKAGE}/{tree}); a wheel built without it "
        f"is incomplete — reinstall, or set {RESOURCE_ROOT_ENV} to a directory "
        f"holding {tree}/."
    )


def resource_path(tree: str, *parts: str) -> Path:
    """Path to a file inside a shipped resource *tree*; raises if absent."""
    resolved = resource_dir(tree).joinpath(*parts)
    if not resolved.exists():
        raise ResourceNotFoundError(
            f"{Path(*parts).as_posix()} is missing from the {tree!r} resource "
            f"tree at {resource_dir(tree)}."
        )
    return resolved
