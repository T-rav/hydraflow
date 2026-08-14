---
id: 2483
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.218629+00:00
status: active
corroborations: 1
supersedes: 2293
---

# Presentational-only Header.jsx changes skip MockWorld layer

Per `docs/standards/testing/README.md`'s three-layer pyramid, a purely presentational change confined to `src/ui/src/components/Header.jsx` only needs unit tests (`Header.test.jsx`) and a browser scenario (`tests/scenarios/browser/workflows/test_orchestrator_controls.py`); no MockWorld scenario. See also: testing — ADR-text + static/unit test fixes skip MockWorld/e2e.

**Why:** MockWorld exists to catch loop integration bugs — forcing it onto UI-only diffs adds no coverage and wastes the layer's purpose as a signal.
