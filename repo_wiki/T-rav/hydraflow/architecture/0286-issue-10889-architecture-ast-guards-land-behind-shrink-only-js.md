---
id: 0286
topic: architecture
source_issue: 10889
source_phase: plan
created_at: 2026-07-31T10:36:59.292297+00:00
status: active
corroborations: 1
---

# Architecture AST guards land behind shrink-only JSON baselines

New AST-scan architecture guards must ship with a shrink-only JSON baseline, not a hand-maintained path list. Precedent: `tests/architecture/adr_enforcement_baseline.json`. New file: `tests/architecture/module_global_reset_baseline.json`. Entries can only be removed, never added. Removing a scanned symbol from `src/` without pruning the baseline fails the guard.

**Why:** Shrink-only prevents baseline rot where stale entries mask missing coverage while blocking silent acceptance of new uncovered globals.
