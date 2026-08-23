"""Module identity — the primitive every path-membership gate matches against.

**The defect class this module closes.** A gate decides something about a
module — "this is a critical path", "this is self-modification", "this loop
needs a kill switch" — by testing a *file path* against a collection of
literal paths or patterns. That works right up until the module is decomposed
into a package. ``src/review_phase.py`` becomes ``src/review_phase/``, the
literal entry stops matching anything, the gate silently stops firing, and
**nothing goes red** — the collection is still there, still imported, still
consulted, just answering ``False`` forever.

It has happened at least eleven times in this repo. Two entries turned out to
name paths that had *never existed at all* (``src/coordinator.py``,
``src/persistence/``) and went unnoticed for months, because a membership test
that matches nothing looks exactly like a membership test that matches nothing
*on this diff*.

The root cause is one line: **a file path was used as a proxy for a module
identity, and the two stopped agreeing.** :func:`module_identities` supplies
the missing vocabulary — ``src/review_phase/_ci.py`` also *is*
``src/review_phase.py``, the module it was before the split. Every gate
matches against those identities rather than the raw path, so membership
follows the MODULE through any decomposition.

This module is deliberately pure: no filesystem reads, no subprocess, no
walking up from ``__file__`` (which resolves inside site-packages in a wheel
install, #11589). The registry of collections under enforcement, and the
repo-wide properties over it, live next to the repo's other structural
scanners in ``tests/architecture/path_membership_registry.py``.
"""

from __future__ import annotations

from pathlib import PurePosixPath

__all__ = ["module_identities"]


def module_identities(path: str) -> tuple[str, ...]:
    """*path* plus the single-file paths it would have had before decomposition.

    ``src/review_phase/_ci.py`` yields ``src/review_phase.py``;
    ``src/health_monitor_loop/_heavy.py`` yields
    ``src/health_monitor_loop.py``. Every intermediate ancestor is walked, so
    nested packages are covered too — ``src/a/b/c.py`` yields ``src/a/b.py``
    and ``src/a.py``.

    Top-level roots are deliberately NOT emitted: ``src`` and ``tests`` are
    directories that were never modules, so ``src.py`` is not an identity any
    caller can mean, and emitting it would let a needle like ``src.py`` match
    every file in the tree — the opposite failure to the one this exists to
    prevent.

    The returned tuple always leads with *path* itself, which is what makes
    every caller's change strictly additive: resolving identities can only
    ever ADD a match, never remove one.
    """
    parts = PurePosixPath(path).parts
    identities = [path]
    # Proper ancestors of depth >= 2 — i.e. every ancestor except the
    # top-level root, which is a directory rather than a decomposed module.
    for depth in range(len(parts) - 1, 1, -1):
        identities.append(f"{PurePosixPath(*parts[:depth]).as_posix()}.py")
    return tuple(identities)
