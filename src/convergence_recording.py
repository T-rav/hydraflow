"""Boundary verdict recording helpers for the convergence pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pending_concerns import Concern


def _normalize_text(text: str) -> str:
    """Strip and collapse internal whitespace for consistent comparison.

    ``" ".join(text.split())`` collapses all runs of whitespace (spaces,
    tabs, newlines) into single spaces and strips leading/trailing whitespace.
    Returns ``""`` for blank input.
    """
    return " ".join(text.split())


def _critical_high_concerns(items: list[Concern]) -> list[str]:
    """Sorted unique concern texts for CRITICAL and HIGH severity items.

    Shared by :func:`signatures_from_concerns` and
    ``adversarial_retry_loop._signature_for`` so both produce equivalent sets.
    """
    return sorted({c.concern for c in items if c.severity in {"CRITICAL", "HIGH"}})


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

    Delegates to :func:`_critical_high_concerns` so the filter + sort logic
    is shared with ``adversarial_retry_loop._signature_for``.
    """
    return _critical_high_concerns(concerns)
