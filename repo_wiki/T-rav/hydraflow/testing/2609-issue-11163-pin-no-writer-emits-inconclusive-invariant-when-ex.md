---
id: 2609
topic: testing
source_issue: 11163
source_phase: review
created_at: 2026-08-14T23:12:52.334776+00:00
status: stale
corroborations: 1
stale_reason: source issue #11163 closed
---

# Pin no-writer-emits-INCONCLUSIVE invariant when excluding from terminal set

When `terminal_ids()` excludes a diagnosis (e.g., `INCONCLUSIVE`) from `_TERMINAL_DIAGNOSES`, that exclusion is only safe if no code path writes that diagnosis to the sidecar. Assert the invariant: after `diagnose()` returns an `INCONCLUSIVE` verdict, the sidecar must stay empty. Add the assertion to the existing inconclusive test rather than creating a new file.

**Why:** An unasserted invariant can silently break when a new writer is added, making the terminal-set scope expansion unsafe.
