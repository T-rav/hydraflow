---
id: 2624
topic: testing
source_issue: 11192
source_phase: plan
created_at: 2026-08-15T00:51:35.394363+00:00
status: active
corroborations: 1
---

# Place ADR.is_live gate before citation assertion, never replace it

In ADR-pinned regression tests like `test_issue_9565.py`, the `ADR.is_live` gate must sit *before* the `source_files` citation check and never replace it.

- Skip on non-live/missing ADR.
- Then assert on `adr.source_files` for live ADRs.

**Why:** Replacing the citation check with the gate makes the underlying assertion vacuous — a Superseded ADR would silently pass regardless of whether it cites nonexistent `dashboard_routes` paths.
