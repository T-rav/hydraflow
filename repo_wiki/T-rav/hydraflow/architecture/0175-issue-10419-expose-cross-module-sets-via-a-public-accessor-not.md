---
id: 0175
topic: architecture
source_issue: 10419
source_phase: plan
created_at: 2026-07-24T07:06:01.754967+00:00
status: active
corroborations: 1
---

# Expose cross-module sets via a public accessor, not a bare import

`src/adr_drift.py` keeps `_SHARED_INFRA_MODULES` private but adds a public `is_shared_infra(path: str) -> bool` wrapper so other modules (e.g. `src/adr_pre_validator.py`) can reuse the set as SSOT without importing a `_`-prefixed symbol across module boundaries.
- Add the public function, don't rename the private set (rename would break #10411's existing regression import).
- Have internal callers like `_citation_drifts` route through the new accessor too, so there's one source of truth.
**Why:** cross-module `_`-prefixed imports are a known gotcha in this repo, and renaming shared private state breaks unrelated in-flight regression tests.
