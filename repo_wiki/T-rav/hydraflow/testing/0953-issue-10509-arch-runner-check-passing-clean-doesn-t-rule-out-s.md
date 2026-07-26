---
id: 0953
topic: testing
source_issue: 10509
source_phase: review
created_at: 2026-07-25T09:54:20.029618+00:00
status: superseded
corroborations: 1
superseded_by: 0954
---

# `arch.runner --check` passing clean doesn't rule out stale regen artifacts

Even when `arch.runner --check` passes, manually diff generated docs under `docs/arch/generated/` for stale `commit_sha` values or duplicate changelog entries left over from a prior regen — these can survive a clean check.

**Why:** `--check` verifies structural consistency, not that every metadata field (like the recorded commit SHA) reflects the latest regen run.
