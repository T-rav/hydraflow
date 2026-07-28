---
id: 1528
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.836910+00:00
status: active
corroborations: 1
supersedes: 1440
---

# Presentational-only Header.jsx changes skip MockWorld layer

Per `docs/standards/testing/README.md`'s three-layer pyramid, a purely presentational change confined to `src/ui/src/components/Header.jsx` — one that crosses no phase or orchestrator behavior — only needs unit tests (`Header.test.jsx`) and a browser scenario (`tests/scenarios/browser/workflows/test_orchestrator_controls.py`); no MockWorld scenario is needed.

Example: see also: testing — Doc+single-unit-test fixes skip MockWorld/e2e.

**Why:** MockWorld exists to catch loop integration bugs — forcing it onto UI-only diffs adds no coverage and wastes the layer's purpose as a signal.
