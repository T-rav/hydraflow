---
id: 0532
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.799108+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Shell-block extractors in regression tests stop at first comment/blank line

Tests like `tests/regressions/test_issue_10408.py` that extract the sync block from `scripts/run-factory-isolated.sh` (reading contiguous non-comment lines after the `[factory] syncing` echo) truncate silently at the first blank or full-line `#` comment.

Example: trailing inline comments on a `git ...` line are safe; a full-line comment inserted between the `checkout -f` / `reset --hard` / `clean -fd` commands truncates the extracted block and silently under-tests the fix.

**Why:** A well-intentioned explanatory comment dropped between the git commands would pass the guard test while leaving `clean -fd` unexercised by the extractor.
