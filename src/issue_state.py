"""The single owner of the 'issue state counts as closed' vocabulary (#11458).

Before this module existed, the membership set of ``PRPort.get_issue_state``
values that mean "closed" was inlined independently at four call sites
(``regression_rot_scan``, ``gate_health_loop``, ``epic``, ``workspace_gc_loop``)
in three different shapes — two of which defensively listed the raw REST
``CLOSED`` value that ``PRManager.get_issue_state`` normalizes away, so the
copies already disagreed on an unreachable value. This module is the one
place that vocabulary lives; every consumer routes through
``issue_state_is_resolved``.

It is deliberately zero-dependency (no config/events/state imports) so pure
engines like ``regression_rot_scan`` and lightweight loops can import it
without dragging in the phase stack. ``phase_utils`` re-exports it for the
phase-layer callers (#11457's import surface).
"""

from __future__ import annotations

# GitHub ``stateReason`` values that mean an issue is done — the vocabulary
# of ``PRPort.get_issue_state`` (OPEN / COMPLETED / NOT_PLANNED / UNKNOWN /
# ``""``). The raw REST ``CLOSED`` value is deliberately absent:
# ``PRManager.get_issue_state`` normalizes it away (a CLOSED issue comes
# back as its ``stateReason``, or ``""`` when null), so it never reaches a
# consumer (#11458).
_RESOLVED_ISSUE_STATES = frozenset({"COMPLETED", "NOT_PLANNED"})


def issue_state_is_resolved(state: object) -> bool:
    """True only for GitHub issue states that mean the issue is resolved (#11457).

    ``COMPLETED`` (fixed) and ``NOT_PLANNED`` (duplicate/wontfix close,
    #10025) are resolved; ``OPEN`` / ``UNKNOWN`` / anything unreadable is
    not. The ``str()`` coercion keeps the predicate fail-open: a caller
    whose Port returns an arbitrary object (an unconfigured ``AsyncMock``
    yields a ``MagicMock``) reads as NOT resolved, so a state re-check built
    on this predicate never blocks a build on a garbage read.
    """
    return str(state or "").upper() in _RESOLVED_ISSUE_STATES
