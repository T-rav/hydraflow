---
id: 1155
topic: testing
source_issue: 10579
source_phase: plan
created_at: 2026-07-26T01:24:12.531358+00:00
status: active
corroborations: 1
---

# Don't delete assertions that encode a UI bug's buggy shape — invert them

`StreamCard.test.jsx:266` asserted `not.toContain('border-left')` for the null-`currentStage` card — that assertion was documenting the defect (missing left border), not verifying correct behavior. When fixing the underlying bug, invert such assertions to check for the *correct* rendered state (e.g. `borderLeftStyle === 'solid'`) rather than deleting them, or coverage for that state silently disappears.

**Why:** deleting a bug-encoding test looks like cleanup but removes the only regression guard for that code path.
