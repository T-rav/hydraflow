---
id: 1400
topic: gotchas
source_issue: 11241
source_phase: plan
created_at: 2026-08-15T10:09:34.777768+00:00
status: active
corroborations: 1
---

# Guard on sanitized value to avoid placeholder collision in close comments

`sanitize_notes_cell()` returns `—` for empty/whitespace-only input. If `_resolution_comment` in `src/escape_ledger_loop.py` guards on the raw `if record.notes:`, a whitespace-only note yields `— —` (placeholder from the sanitizer plus the close-comment separator). Fix: `sanitize_notes_prose()` returns empty string for whitespace-only input, and the guard tests the sanitized value.

**Why:** Testing the raw value before sanitization lets hostile input bypass the empty-check, producing dangling separators in filed issue bodies.
