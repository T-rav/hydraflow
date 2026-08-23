"""Module-level helpers and edge guards for the ``implement_phase`` package.

Split out of the original ``src/implement_phase.py`` (god-class decomposition,
Refs #11547) so the mixin modules have a cycle-free home for the shared
module-level surface: the flow diagram that documents the graph in ``_flow.py``,
its four edge guards, and the pinned-adequacy-demand helper ``_build.py`` reads.
Everything here is re-exported from ``implement_phase/__init__.py`` for
back-compat — external callers continue to do ``from implement_phase import X``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from adequacy_demand import pin_findings

if TYPE_CHECKING:
    from flows import FlowState
    from models import WorkerResult

logger = logging.getLogger("hydraflow.implement_phase")


# ---------------------------------------------------------------------------
# Implement flow (P2 of #10682, ADR-0111) — edge guards
# ---------------------------------------------------------------------------
#
# The per-issue implement pipeline runs as an explicit ``src.flows.Flow``:
#
#     decompose -> no-progress-abort -> issue-state -> build -> screen
#         screen  --(zero-commit)-------------------> zero-commit-abort
#             zero-commit-abort --(routed to diagnose, #11568)--> done
#             zero-commit-abort --(abort disabled / below threshold)--> spec-verify
#         screen  --(null-delivery)-----------------> spec-verify -> gate -> done
#         screen  --(otherwise)---------------------> open-pr
#         open-pr --(success / early-return)--------> done
#         open-pr --(failed retry / no-PR failure)--> spec-verify -> gate -> done
#
# Every fail-closed early-exit (existing-PR shortcut, attempt-cap, no-progress
# abort, zero-commit abort, ``_handle_successful_push`` early return) sets
# ``state['_stop']`` and
# routes straight to the terminal ``done`` sink. The LLM/agent call lives inside
# ``build`` alone (the actuator boundary); routing between nodes is
# deterministic. The graph is reused two ways: ``_worker_inner`` runs it from
# ``decompose``; ``_handle_implementation_result`` re-enters it at ``screen``
# (``Flow.resume``) with the built ``result`` pre-seeded, so the post-build
# handling has a single source of truth.


def _flow_stopped(state: FlowState) -> bool:
    """Edge guard: a node signalled a fail-closed early exit → route to ``done``."""
    return bool(state.get("_stop"))


def _route_is_zero_commit(state: FlowState) -> bool:
    """Edge guard: ``screen`` classified a zero-commit failure (#11568).

    Zero-commit results visit ``zero-commit-abort`` first: at/over the
    ``implement_no_progress_abort_attempts`` threshold (default 1 — the
    FIRST such result) the issue routes to diagnose and the walk ends;
    otherwise it falls through to ``spec-verify`` like any other failure.
    """
    return state.get("route") == "fail_zero_commit"


def _route_is_failure_screen(state: FlowState) -> bool:
    """Edge guard: ``screen`` classified a zero-commit / null-delivery failure.

    These are the two failures that never push and go straight to the shared
    ``spec-verify`` node (screen-specific comment + spec-compliance review).
    Every other classification (success, retry-push, committed-but-failed,
    no-workspace) flows through ``open-pr`` first. Zero-commit results reach
    here only via ``zero-commit-abort`` (its first-match edge wins).
    """
    return state.get("route") in {"fail_zero_commit", "fail_null_delivery"}


def _pinned_adequacy_demand(result: WorkerResult) -> list[str]:
    """The test-adequacy demand to carry onto the next attempt (#11644).

    Empty unless this attempt actually died at the adequacy gate. Only the
    findings that BLOCKED ride forward: advisory findings (new *and* naming
    nothing locatable) did not reject this run, so promoting them to the next
    run's bar would reintroduce exactly the moving target the pin removes.
    """
    outcome = result.test_adequacy
    if outcome is None or outcome.passed:
        return []
    advisory = set(outcome.advisory_findings)
    return list(pin_findings([f for f in outcome.findings if f not in advisory]))


def _open_pr_terminal(state: FlowState) -> bool:
    """Edge guard: ``open-pr`` fully resolved the outcome → route to ``done``.

    True on an early return (no-PR fallback / zero-diff escalation set
    ``_stop``) or on a genuine success. A failed push path (a failed
    review-feedback retry, or a committed-but-failed fresh attempt) instead
    falls through to ``spec-verify`` so the two-stage reviewer still captures
    gaps for the next attempt (ADR-0063 W5).
    """
    return bool(state.get("_stop")) or bool(state["result"].success)
