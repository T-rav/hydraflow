---
id: 1402
topic: gotchas
source_issue: 11247
source_phase: plan
created_at: 2026-08-15T20:03:13.665768+00:00
status: active
corroborations: 1
---

# Seed FakeIssue/FakePR timestamps relative to the loop window

Seed `created_at`/`closed_at`/`merged_at` on `FakeIssue`/`FakePR` relative to the loop's fitness window via `add_issue`/`add_pr` or `set_issue_closed_at`.

- `FakeIssue.created_at` defaults to the fixed `2026-01-01T00:00:00Z`, which falls outside the live fitness window.
- A scenario that seeds issues without overriding timestamps reads INSUFFICIENT_DATA and asserts nothing.

**Why:** Fixed-default timestamps silently produce empty fitness windows, making regression scenarios pass vacuously.
