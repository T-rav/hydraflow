---
id: 0339
topic: architecture
source_issue: 11185
source_phase: plan
created_at: 2026-08-14T23:55:43.383222+00:00
status: active
corroborations: 1
---

# Run full make quality for shared renderer changes

When modifying a shared renderer like `src/escape/report.py`, run the full `make quality` suite, not a file-targeted test subset.

- Other test modules assert on ledger markdown structure and may break when column counts or cell formatting change.
- Any existing test asserting the old 8-cell row shape must be updated in the same commit, not deleted.

**Why:** File-targeted runs miss structural assertions in sibling test files that depend on the renderer's output format.
