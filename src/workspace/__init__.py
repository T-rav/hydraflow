"""Back-compat re-exports for the ``workspace`` package.

``src/workspace.py`` held a 970-LOC, 41-method ``WorkspaceManager``. Split for
mass discipline (Refs #11547), the shape ``agent/``, ``reviewer/`` and
``review_phase/`` already use. Existing imports keep working::

    from workspace import WorkspaceManager   # still works

Layout:
  * ``_manager.py``   — construction, the locks, create/destroy, and the
    pre/post-work hooks callers reach for: what the class IS.
  * ``_provision.py`` — everything a fresh worktree needs before work starts.
  * ``_heal.py``      — repair paths for a worktree that is already wrong.
    Separate from provisioning because provisioning runs once on a clean tree
    and healing runs against one somebody else left broken.
  * ``_mainline.py``  — merge, reset, and the questions asked about divergence.
  * ``_remote.py``    — git primitives about origin, and their retry discipline.

Each slice is a mixin ``WorkspaceManager`` inherits, so there is exactly ONE
class identity and every ``patch.object(WorkspaceManager, ...)`` still resolves.

**Patch targets follow their call site.** A module-level name a test reaches
through is bound in the module that CALLS it, so ``patch("workspace.X")`` would
replace an attribute here and leave the real binding untouched — a patch that
silently no-ops. Patch ``workspace._provision.X`` / ``workspace._remote.X``
instead, so a stale target fails loudly.
"""

from __future__ import annotations

from ._manager import _FETCH_LOCKS, _WORKTREE_LOCKS, WorkspaceManager

#: Re-exported deliberately, and this is the ONE case where re-exporting is
#: right. A function binding re-exported here would be a second name for the
#: same callable and patching it would leave each slice's own binding untouched
#: — a patch that silently no-ops. A shared mutable registry is the opposite:
#: ``workspace._FETCH_LOCKS is workspace._manager._FETCH_LOCKS``, so the
#: single-registry invariant #6697 and #7839 pin holds through the package.
__all__ = ["WorkspaceManager", "_FETCH_LOCKS", "_WORKTREE_LOCKS"]
