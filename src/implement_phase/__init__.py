"""Back-compat re-exports for the ``implement_phase`` package.

The original ``src/implement_phase.py`` (2282 lines / a 1845-LOC, 61-method
``ImplementPhase``) was split into this package for mass discipline
(Refs #11547), the same shape ``review_phase/`` already uses. All existing
imports keep working::

    from implement_phase import ImplementPhase   # still works
    import implement_phase                       # still works

Layout:
  * ``_common.py``      — the flow diagram, its four edge guards, the
    pinned-adequacy-demand helper, and the package logger.
  * ``_phase.py``       — the ``ImplementPhase`` class: construction, the
    ``run_batch`` slot-filling pool, the flow entry points, transcript hooks.
  * ``_flow.py``        — the ADR-0111 flow graph and every node body.
  * ``_build.py``       — build preparation and the agent run itself.
  * ``_beads.py``       — the per-worktree Beads task-graph lifecycle.
  * ``_screen.py``      — build-outcome screening (zero-commit / null-delivery).
  * ``_abort.py``       — the early-abort / attempt-cap / escalation gates.
  * ``_spec_review.py`` — the ADR-0063 W5 spec-compliance review.
  * ``_pr.py``          — push → PR resolution, recovery, and hand-off.

Each slice is a mixin ``ImplementPhase`` inherits, so there is exactly ONE
class identity and every ``patch.object(ImplementPhase, ...)`` target still
resolves.
"""

from __future__ import annotations

from ._common import (
    _flow_stopped,
    _open_pr_terminal,
    _pinned_adequacy_demand,
    _route_is_failure_screen,
    _route_is_zero_commit,
    logger,
)
from ._phase import ImplementPhase

__all__ = [
    "ImplementPhase",
    "_flow_stopped",
    "_open_pr_terminal",
    "_pinned_adequacy_demand",
    "_route_is_failure_screen",
    "_route_is_zero_commit",
    "logger",
]
