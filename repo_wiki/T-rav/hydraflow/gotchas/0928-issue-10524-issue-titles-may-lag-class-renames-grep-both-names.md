---
id: 0928
topic: gotchas
source_issue: 10524
source_phase: plan
created_at: 2026-07-25T07:08:18.759709+00:00
status: superseded
corroborations: 1
superseded_by: 0940
---

# Issue titles may lag class renames — grep both names before scoping

Issue #10524 names `ADRReviewer` but the live class is `ADRCouncilReviewer` in `src/adr_reviewer.py`. Grep for both the issue's named symbol and the actual current class (plus any re-export/alias) before declaring call sites covered.

**Why:** scoping call-site changes off the issue title alone risks missing renamed classes and leaving stale references unfixed.
