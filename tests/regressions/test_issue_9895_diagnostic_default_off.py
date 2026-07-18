"""Regression: DiagnosticLoop credit-flood → default the loop OFF (#9895).

DiagnosticLoop analyzes failed-issue *transcripts*, which quote credit-error
prose ("usage limit reached", "credit balance is too low"). Its streaming
runner's ``is_credit_exhaustion`` matched that quoted prose → a false
``CreditExhaustedError`` on nearly every run → the orchestrator suppressed the
pause (credit-probe fix) but the loop tight-restarted → a log flood (36k+ lines,
550MB events.jsonl, event loop starved), plus event-loop blocking (#9879).

Runtime kill-switches didn't hold: ``CostBudgetWatcher`` re-enabled the runtime
bg-worker, and the base ``config.json`` override didn't reach the per-repo
runtime's ``HydraFlowConfig`` (which inherited the default). The fix defaults the
deploy-time kill-switch OFF so *every* config construction — base and per-repo
runtime — inherits it, above the runtime enable (cost-budget-proof) and
restart-proof. Re-enable only after #9879/#9888 + the transcript-analysis
credit-detection fix land.
"""

from __future__ import annotations

from config import HydraFlowConfig


def test_diagnostic_loop_disabled_by_default() -> None:
    """A fresh config (no override) must have the DiagnosticLoop kill-switch OFF."""
    assert HydraFlowConfig().diagnostic_loop_enabled is False
