---
id: 0484
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.404548+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0494
---

# Regression tests that extract shell blocks from scripts stop at first comment/blank line

Tests like `tests/regressions/test_issue_10408.py` that extract the sync block from `scripts/run-factory-isolated.sh` (reading contiguous non-comment lines after the `[factory] syncing` echo) truncate silently at the first blank or full-line `#` comment. Trailing inline comments on a `git ...` line are safe; a full-line comment inserted *between* the `checkout -f` / `reset --hard` / `clean -fd` commands truncates the extracted block and silently under-tests the fix.

**Why:** a well-intentioned explanatory comment dropped between the git commands would pass the guard test while leaving `clean -fd` unexercised by the extractor.
