---
id: 0583
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.223013+00:00
status: superseded
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
superseded_by: 0593
---

# Shell-block extractors in regression tests stop at first comment/blank line

Tests like `tests/regressions/test_issue_10408.py` that extract the sync block from `scripts/run-factory-isolated.sh` (reading contiguous non-comment lines after the `[factory] syncing` echo) truncate silently at the first blank or full-line `#` comment.

Example: trailing inline comments on a `git ...` line are safe; a full-line comment inserted between the `checkout -f` / `reset --hard` / `clean -fd` commands truncates the extracted block and silently under-tests the fix.

**Why:** A well-intentioned explanatory comment dropped between the git commands would pass the guard test while leaving `clean -fd` unexercised by the extractor.
