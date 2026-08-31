---
id: 2787
topic: testing
source_issue: 11548
source_phase: plan
created_at: 2026-08-30T10:39:26.773613+00:00
status: active
corroborations: 1
---

# Parametrised guards need registry ∪ gap == loop_units() or they measure less

A loop-skeleton sweep that silently covers only the easy loops makes the suite look better while measuring less — `docs/standards/parametrised_guards/README.md` F2. Require:

- A runtime scan (`tests.loop_module_scan.loop_units()`), never a hardcoded path list.
- A shrink-only gap list so `registry ∪ gap == loop_units()`.
- Sweep fails when registry is empty, when a live loop is missing from both, or when a gap entry names a non-existent loop.

**Why:** Without both equality and the shrink-only ratchet, coverage reads as total when it isn't.
