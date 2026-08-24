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
instead, so a stale target fails loudly. This holds for module-level DATA too,
which is why ``_FETCH_LOCKS`` and ``_WORKTREE_LOCKS`` are deliberately NOT
re-exported here; see below.

**Nothing else is re-exported, on purpose.** The first cut of this module also
re-exported ``_FETCH_LOCKS`` / ``_WORKTREE_LOCKS``, reasoning that a shared
mutable registry is safe to alias because ``workspace._FETCH_LOCKS is
workspace._manager._FETCH_LOCKS`` — mutate either name, both see it. True, and
irrelevant: no consumer mutates them. Both consumers *rebind* them, via
``patch.object(workspace, "_FETCH_LOCKS", racy_dict)``, and rebinding sets the
attribute on THIS module while ``_repo_fetch_lock`` keeps reading
``_manager.__dict__``. So the alias bought nothing real and cost the loud
failure: the four #6697/#7839 TOCTOU guards patched a name that resolved, never
opened the race window they exist to open, and stayed green for a full release
with the check-then-set bug reintroducible at will (#11547 review).

Without the re-export, ``patch.object(workspace, "_FETCH_LOCKS", ...)`` raises
``AttributeError`` — which is the whole point. Reach the registries at
``workspace._manager._FETCH_LOCKS``, the module that defines and reads them.
"""

from __future__ import annotations

from ._manager import WorkspaceManager

__all__ = ["WorkspaceManager"]
