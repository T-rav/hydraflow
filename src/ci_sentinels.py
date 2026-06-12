"""Shared CI wait-result sentinels (single source of truth).

``PRManager.wait_for_ci`` returns a free-form ``(passed, summary)`` tuple.
Callers (notably :class:`StagingPromotionLoop`) branch on ``summary`` to tell a
real CI *failure* apart from an *incomplete* wait — the poll window elapsed
while CI was still running, or the kill-switch fired. Those non-failure cases
must be retried, not treated as a failure (closing a still-green PR).

Historically the producer (``pr_manager``) and the consumer (the loop)
hard-coded these strings independently and they DRIFTED: the producer emitted
``"Timeout after 60s"`` while the loop guarded on the literal ``"timed out"`` —
which that string does not contain — so every slow-CI tick force-closed a GREEN
rc PR and the staging→main pipeline silently stalled for ~3 days (issues
#9219..#9342, fixed in #9351). This module makes the sentinels AND the
"incomplete → retry" classification one shared symbol so producer and consumer
can never drift again. A contract test pins it.
"""

from __future__ import annotations

# wait_for_ci returns this when the kill-switch fires mid-poll — not a failure.
CI_STOPPED = "Stopped"

_CI_TIMEOUT_PREFIX = "Timeout after "


def ci_timeout(timeout: int) -> str:
    """Summary ``wait_for_ci`` returns when the poll window elapses with CI
    still pending (not a failure — retry on the next tick)."""
    return f"{_CI_TIMEOUT_PREFIX}{timeout}s"


def is_ci_incomplete(summary: str) -> bool:
    """``True`` when ``wait_for_ci`` returned WITHOUT a CI verdict — it timed out
    while CI was still running, or was stopped by the kill-switch. Such a PR must
    be left open and retried, NOT treated as a CI failure. ``False`` for a real
    failure summary (e.g. ``"ci failed: scenario tests"``)."""
    return (
        summary == CI_STOPPED
        or summary.startswith(_CI_TIMEOUT_PREFIX)
        # Defensive: tolerate any legacy/alternate "timed out" phrasing too.
        or "timed out" in summary.lower()
    )
