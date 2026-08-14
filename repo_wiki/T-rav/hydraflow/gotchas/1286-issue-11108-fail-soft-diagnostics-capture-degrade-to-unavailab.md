---
id: 1286
topic: gotchas
source_issue: 11108
source_phase: plan
created_at: 2026-08-14T09:10:42.283905+00:00
status: active
corroborations: 1
---

# Fail-soft diagnostics capture: degrade to unavailable(reason), never raise

Diagnostics sections appended to anomaly issues must each degrade to `unavailable (<reason>)` on failure rather than raising. Capture is deadline-bounded by `trust_fleet_diagnostics_budget_seconds`.

- Missing trace dir → `unavailable (no trace directory)`.
- Past-deadline → remaining sections marked `budget_exhausted`.
- `_file_anomaly` still returns the issue number even if capture raises.

**Why:** Diagnostics are a best-effort enrichment of the issue body; aborting filing on capture failure defeats the purpose of reporting the anomaly.
