---
id: 1610
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.423685+00:00
status: superseded
corroborations: 1
supersedes: 1528
superseded_by: 1693
---

# Presentational-only Header.jsx changes skip MockWorld layer

Per docs/standards/testing/README.md's three-layer pyramid, a purely presentational change confined to src/ui/src/components/Header.jsx only needs unit tests (Header.test.jsx) and a browser scenario (tests/scenarios/browser/workflows/test_orchestrator_controls.py); no MockWorld scenario.

Example: see also: testing — Doc+single-unit-test fixes skip MockWorld/e2e.

**Why:** MockWorld exists to catch loop integration bugs — forcing it onto UI-only diffs adds no coverage and wastes the layer's purpose as a signal.
