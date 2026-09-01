---
id: 0310
topic: dependencies
source_issue: 11869
source_phase: plan
created_at: 2026-09-01T05:42:49.576671+00:00
status: active
corroborations: 1
---

# policy.models re-exports Charter — no bridge needed for articles.assurance

Do not add bridge functions to reach `articles.assurance`; `src/policy/models.py` already re-exports `charter_model.Charter`. Thread the charter object directly into `_decide_enforcement`.

The findings doc's `seam_charter()` helper is obsolete for this purpose.

**Why:** A bridge duplicates the import path and creates a second source of truth for charter access, increasing the surface for drift.
