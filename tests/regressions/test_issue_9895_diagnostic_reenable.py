"""Regression: DiagnosticLoop re-enabled after the #9895 blockers landed.

The loop was defaulted OFF during the credit-flood incident (#9895/#9898):
its diagnosis agents quote credit-error prose from failed issues'
transcripts, false-tripping is_credit_exhaustion on nearly every run, and
Stage 1 starved the event loop. The OFF-default pin listed three explicit
re-enable conditions; ALL landed:

- #9888  false-positive credit cooldown/backoff at the orchestrator,
- #10001 CREDIT_PROSE_SCAN opt-out (stderr-only detection for the
         diagnostic runner) + HITL comment dedup,
- #10018 (#9879) gate_prompt off-thread + TAIL-capped ci_logs/pr_diff.

This pin now guards the ON default: turning it back off is an operator
decision (env override), not silent drift — and the kill-switch itself
must survive for the next incident.
"""

from __future__ import annotations

from config import HydraFlowConfig


def test_diagnostic_loop_enabled_by_default_post_reenable() -> None:
    """All #9895 re-enable conditions landed — a fresh config runs the loop."""
    assert HydraFlowConfig().diagnostic_loop_enabled is True
