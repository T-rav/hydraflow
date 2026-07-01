"""Boundary verdict recording helpers for the convergence pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pending_concerns import Concern


def record_stage_verdict(
    state: Any,
    *,
    issue_number: int,
    stage: str,
    decision: str,
    signatures: list[str],
) -> None:
    """Record a boundary verdict into the per-issue ConvergenceLedger.

    Records verdict + signatures ONLY (does NOT mark_lap or
    recompute_converged — those stay review-owned).
    """
    ledger = state.ensure_convergence_ledger(issue_number)
    ledger.record_gate_result(stage, decision, signatures)
    state.save_convergence_ledger(issue_number, ledger)


def signatures_from_concerns(concerns: list[Concern]) -> list[str]:
    """Sorted unique CRITICAL/HIGH concern texts.

    Mirrors ``adversarial_retry_loop._signature_for`` filtering logic.
    """
    return sorted({c.concern for c in concerns if c.severity in {"CRITICAL", "HIGH"}})
