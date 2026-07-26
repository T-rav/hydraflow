---
id: 1158
topic: testing
source_issue: 10583
source_phase: plan
created_at: 2026-07-26T02:28:58.639395+00:00
status: active
corroborations: 1
---

# gotchas.md entries should be pinned by a test citing the guard's path

New `docs/wiki/gotchas.md` entries for a code-level rule (e.g. the border-shorthand rule) should be paired with a test asserting the entry exists and cites the actual guard test's file path (e.g. `src/ui/src/test/__tests__/borderShorthandScan.test.js`), so moving or renaming the guard breaks the docs test instead of silently going stale. Also verify the entry's `json:entry` block parses as valid JSON alongside existing entries.

**Why:** keeps the wiki's machine-readable knowledge base (per ADR-0032) in sync with the code it documents, rather than drifting after a refactor.
