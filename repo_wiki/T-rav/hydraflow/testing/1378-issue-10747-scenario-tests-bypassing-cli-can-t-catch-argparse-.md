---
id: 1378
topic: testing
source_issue: 10747
source_phase: review
created_at: 2026-07-27T23:55:24.611778+00:00
status: stale
corroborations: 1
stale_reason: source issue #10747 closed
---

# Scenario tests bypassing CLI can't catch argparse regressions

Scenario tests in `tests/scenarios/` that call service functions directly (e.g., `resolve_escape()`) rather than the operator CLI (`scripts/resolve_escape.py`) cannot catch argparse-layer regressions end-to-end through the reconcile pass.

When a separate CLI unit test covers the same path (e.g., `test_cli_resolve_confidence_only_succeeds_without_encoded_as`), aggregate coverage across the pyramid is acceptable, but note the gap for awareness. Wiring MockWorld scenarios through the real CLI is a nice-to-have, not a blocker.

**Why:** Driving the service layer skips the exact boundary — argparse `required` relaxation — where input-validation regressions originate.
