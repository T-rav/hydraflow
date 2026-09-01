---
id: 2790
topic: testing
source_issue: 11862
source_phase: plan
created_at: 2026-09-01T03:40:49.615518+00:00
status: active
corroborations: 1
---

# Widen all three purity allow-lists in test_policy_engine_is_pure.py when extending python_engine

`src/policy/python_engine.py` is pinned per-symbol, per-builtin, and per-annotation in `test_policy_engine_is_pure.py` via `_PURE_IMPORTS`, `_PURE_BUILTINS`, `_PURE_ANNOTATIONS`. Adding a new decision arm that imports `charter_model` finding constants or annotates with `float` requires widening **all three** lists — never suppress or skip.

Example: adding `_decide_charter` meant allow-listing `policy.facts.STANDARD_CHARTER`, `charter_model` finding constants, and `float`.

**Why:** Suppressing the guard instead of widening it silently lets a file-reading import into the pure engine, breaking the facts/decisions/world-reading seam split from ADR-0143 Ruling 5.
