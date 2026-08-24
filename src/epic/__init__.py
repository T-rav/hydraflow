"""Back-compat re-exports for the ``epic`` package.

``src/epic.py`` held a 898-LOC, 36-method ``EpicManager`` alongside a
456-line ``EpicCompletionChecker`` and seven free functions. Split for mass
discipline (Refs #11547), the shape ``agent/``, ``reviewer/``, ``workspace/``
and ``pr_unsticker/`` already use. Existing imports keep working::

    from epic import EpicManager, EpicCompletionChecker   # still works
    from epic import parse_epic_sub_issues                # still works

Layout:
  * ``_manager.py``    — construction, ``register_epic``, and the two
    write-side primitives every slice ends with (``_invalidate_cache`` /
    ``_publish_update``): what the class IS.
  * ``_children.py``   — the five label-driven child callbacks and auto-close.
  * ``_progress.py``   — the counted view of an epic and its freshness test.
  * ``_detail.py``     — the dashboard read-model and its cache.
  * ``_child_info.py`` — per-child enrichment. Separate from ``_detail``
    because it breaks for different reasons: a detail breaks when the epic's
    shape changes, a child row breaks when GitHub or the worker fleet reports
    a child differently.
  * ``_merge_order.py``— merge coordination under each strategy (ADR-0012).
  * ``_release.py``    — the operator trigger, the authorisation layering, and
    the merge run. Owns ``ReleaseEpicResultError``, which only it raises.
  * ``_staleness.py``  — the caretaker sweep over epics that stopped moving.
  * ``_completion.py`` — ``EpicCompletionChecker``: a separate collaborator,
    not a slice of the manager. It is constructed independently and owns the
    module's only ``generate_changelog`` call.
  * ``_parse.py``      — pure readers turning GitHub text and config strings
    into typed values. Each compiled pattern lives with its one consumer.

The manager's slices are mixins ``EpicManager`` inherits, so there is exactly
ONE class identity and every ``patch.object(EpicManager, ...)`` still resolves.

**Patch targets follow their call site.** A module-level name a test reaches
through is bound in the module that CALLS it, so ``patch("epic.X")`` would
replace an attribute here and leave the real binding untouched — a patch that
silently no-ops, and one that passes. ``generate_changelog`` is bound in
``epic._completion``; ``logger`` is bound in every slice (they are all the same
``logging.getLogger("hydraflow.epic")`` object, so mutating IT is fine — naming
the wrong module is not); ``ReleaseEpicResultError`` is defined in
``epic._release``. Patch those, not this module.

Only the two CLASSES ``src/`` imports plus the two epic-body parsers it calls
are re-exported. Class re-exports are identity-safe (``isinstance`` and
``patch.object`` both still work through them). The two functions are here
because ``epic_sweeper_loop`` imports them by that name; they are pure
functions of a string, nothing patches them today, and anything that wants to
must patch ``epic_sweeper_loop.parse_epic_sub_issues`` — the call site's own
binding — never this one. Everything else (``ReleaseEpicResultError``,
``_stage_from_labels``, ``extract_version_from_title``, ``WorkerTruthStore``)
is deliberately NOT re-exported so a stale target raises instead of no-opping.
"""

from __future__ import annotations

from ._completion import EpicCompletionChecker
from ._manager import EpicManager
from ._parse import check_all_checkboxes, parse_epic_sub_issues

__all__ = [
    "EpicCompletionChecker",
    "EpicManager",
    "check_all_checkboxes",
    "parse_epic_sub_issues",
]
