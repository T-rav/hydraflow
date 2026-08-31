---
id: 1542
topic: gotchas
source_issue: 11544
source_phase: plan
created_at: 2026-08-30T15:37:21.169335+00:00
status: active
corroborations: 1
---

# Fail routing migration on non-empty effective matrix diffs

When compiling legacy dials into baseline `RoutingPolicy` rows via `PolicyWorkspace.apply`, gate the migration commit on an empty `diff_matrices` result.

Example: Compare the effective routing matrix before and after compiling `repo_provider` and `maintenance_provider` dials. Fail loudly if the matrices diverge before allowing the audited revision.

**Why:** Compiling dials into policies can silently shift an effective route, breaking the reversibility guarantee of the `ROLLBACK` mutation.
