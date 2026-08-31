"""Module-level constants and helpers shared by the ``plan_phase`` mixins.

Extracted VERBATIM from ``plan_phase.py`` (god-class decomposition, Refs
#11547). ``plan_phase`` imports every mixin module, so a mixin cannot import
``plan_phase`` back — the names both sides need live here instead. Same role as
``pr_manager_common.py`` from #11628. Every name is re-exported from
``plan_phase`` so the historical ``from plan_phase import _PRIORITY_LABELS``
seam keeps working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flows import flow_stopped

if TYPE_CHECKING:
    pass

# Verdict map for ConvergenceLedger boundary recording (ADR-0096 / convergence gate).
# "ADVANCE" = issue moves forward in the pipeline.
# "LOOP_BACK" = issue failed planning and must re-enter the plan stage.
# "ESCALATE" = issue is handed off to HITL.
_PLAN_VERDICT_MAP: dict[str, str] = {
    "success": "ADVANCE",
    "failed": "LOOP_BACK",
    "escalated": "ESCALATE",
}

# Minimum body length for auto-filed sub-issues discovered during planning.
_MIN_ISSUE_BODY_CHARS: int = 50

# Priority labels IssueRefinementLoop manages (#9957). Mirrors
# ``issue_refinement_loop._PRIORITY_LABELS`` — an unprioritized shape fork is
# deferred, not HITL-escalated (#10311).
_PRIORITY_LABELS: tuple[str, ...] = ("P0", "P1", "P2")


#: Canonical since #11803 — re-exported under the existing private name so
#: every call site in this package keeps working unchanged. The three former
#: copies were byte-identical, so this is a move, not a semantic merge.
_flow_stopped = flow_stopped
