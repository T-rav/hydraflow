"""Single owner of the "issue state means closed" vocabulary (#11458).

The set of ``PRPort.get_issue_state`` values that count as closed was
previously written out independently in four places (regression_rot_scan,
gate_health_loop, epic, workspace_gc_loop) in three different shapes, and
they disagreed on whether the raw REST ``CLOSED`` value belongs. It does
not: ``PRManager.get_issue_state`` normalizes ``CLOSED`` into its
``stateReason`` (``COMPLETED`` / ``NOT_PLANNED`` / ``""``) before the value
escapes the port, so ``CLOSED`` is unreachable from the real port and the
two call sites that included it were defending a value that never arrives.

This module is a zero-dependency leaf so pure-stdlib scanners can import
it without pulling in heavyweight phase modules; ``phase_utils`` re-exports
the predicate for patches that pin ``phase_utils`` as the import surface.
"""

from __future__ import annotations

# Issue states (as returned by ``PRPort.get_issue_state``) that mean the
# issue is closed.
RESOLVED_ISSUE_STATES = frozenset({"COMPLETED", "NOT_PLANNED"})


def issue_state_is_resolved(state: object) -> bool:
    """True only for issue states that mean the issue is resolved.

    ``COMPLETED`` (fixed) and ``NOT_PLANNED`` (duplicate/wontfix close) are
    resolved; ``OPEN`` / ``UNKNOWN`` / anything unreadable is not. The
    ``str()`` coercion keeps the predicate fail-open: a caller whose port
    returns an arbitrary object (an unconfigured ``AsyncMock`` yields a
    ``MagicMock``) reads as not resolved, so logic built on this predicate
    never treats a garbage read as a closed issue.
    """
    return str(state or "").upper() in RESOLVED_ISSUE_STATES
