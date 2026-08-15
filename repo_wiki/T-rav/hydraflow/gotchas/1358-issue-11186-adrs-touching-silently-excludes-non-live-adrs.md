---
id: 1358
topic: gotchas
source_issue: 11186
source_phase: plan
created_at: 2026-08-15T00:14:35.607936+00:00
status: active
corroborations: 1
---

# adrs_touching silently excludes non-live ADRs

`adrs_touching` filters out superseded and non-live ADRs from its results. Tests asserting drift on a superseded ADR — e.g., ADR-0064's deliberately-bare data/prompt modules in `test_issue_9419_9421_adr_drift.py` — fail because the ADR is dropped, not because drift is absent.

**Why:** Superseding a pinned ADR produces test failures that look like citation drift but are actually liveness filtering.
