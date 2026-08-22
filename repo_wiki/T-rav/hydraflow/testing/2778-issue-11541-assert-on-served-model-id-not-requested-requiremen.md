---
id: 2778
topic: testing
source_issue: 11541
source_phase: plan
created_at: 2026-08-22T00:00:10.177894+00:00
status: active
corroborations: 1
---

# Assert on served model id, not requested requirement

When testing literal-model resolution (`claude-opus`, `claude-sonnet`), assert on the served model id recorded in the receipt — never on the requested requirement string.

- `tests/regressions/test_issue_11541.py` must pin "literal Opus never served by GLM."
- A capability-class fallback path (e.g. from #11540) can silently satisfy `claude-opus` with a GLM route unless the served-model assertion catches it.

**Why:** A pool/fallback route can match the requirement name while delivering a different model family, making the literal-resolution guarantee unenforced.
