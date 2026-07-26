---
id: 1149
topic: testing
source_issue: 10592
source_phase: plan
created_at: 2026-07-26T03:33:58.716473+00:00
status: active
corroborations: 1
---

# Presentational-only Header.jsx changes skip the MockWorld layer of the test pyramid

Per `docs/standards/testing/README.md`'s three-layer pyramid (unit + MockWorld scenario + sandbox e2e), a purely presentational change confined to `src/ui/src/components/Header.jsx` — one that crosses no phase or orchestrator behavior — only needs unit tests (`Header.test.jsx`) and a browser scenario (`tests/scenarios/browser/workflows/test_orchestrator_controls.py`); no MockWorld scenario is needed since there's no loop/orchestrator integration to catch.

**Why:** MockWorld exists to catch loop integration bugs — forcing it onto UI-only diffs adds no coverage and wastes the layer's purpose as a signal.
