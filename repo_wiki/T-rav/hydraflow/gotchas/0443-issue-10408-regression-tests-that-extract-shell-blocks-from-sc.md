---
id: 0443
topic: gotchas
source_issue: 10408
source_phase: plan
created_at: 2026-07-24T05:56:46.873237+00:00
status: active
corroborations: 1
---

# Regression tests that extract shell blocks from scripts stop at first comment/blank line

Tests like `tests/regressions/test_issue_10408.py` that extract the sync block from `scripts/run-factory-isolated.sh` (reading contiguous non-comment lines after the `[factory] syncing` echo) truncate silently at the first blank or full-line `#` comment. Trailing inline comments on a `git ...` line are safe; a full-line comment inserted *between* the `checkout -f` / `reset --hard` / `clean -fd` commands truncates the extracted block and silently under-tests the fix.

**Why:** a well-intentioned explanatory comment dropped between the git commands would pass the guard test while leaving `clean -fd` unexercised by the extractor.
