---
id: 1365
topic: gotchas
source_issue: 11195
source_phase: plan
created_at: 2026-08-15T01:07:17.474000+00:00
status: active
corroborations: 1
---

# Commit untracked reproduction guards verbatim, do not regenerate

When a reproduction guard already exists as an untracked file (e.g. `tests/regressions/test_issue_11195.py`), commit it as-is.

- Regenerating rewrites the differential baseline that distinguishes RED from GREEN phases.
- The guard's value is its fixed shape across both phases of the task graph.

**Why:** Rewriting the guard loses its baseline and can introduce flakiness or mask the exact failure mode it was designed to catch.
