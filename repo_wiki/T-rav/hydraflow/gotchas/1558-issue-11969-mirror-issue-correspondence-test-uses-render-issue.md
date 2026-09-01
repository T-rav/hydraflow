---
id: 1558
topic: gotchas
source_issue: 11969
source_phase: plan
created_at: 2026-09-01T11:15:55.080244+00:00
status: active
corroborations: 1
---

# Mirror-issue correspondence test uses render_issue_body footer

To decide whether an `issue-open` pin in `MemoryBacklogLoop` belongs to a mirror, use the predicate: *issue body contains the mirror's repo-relative path AND state is OPEN*. Every issue the loop files carries `- Mirror: [`<relpath>`](<relpath>)` (emitted by `render_issue_body`), so body-path containment is the exact "this is my issue" test.

Example: a pin to #11949 (body names the mirror) → keep; a pin to #27 (body names a different path) → reset to `pending`.

**Why:** A pure, stateless predicate survives issue-number reuse and stale pins without needing a second index.
