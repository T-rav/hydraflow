---
id: 0847
topic: gotchas
source_issue: 10499
source_phase: review
created_at: 2026-07-25T06:08:03.278840+00:00
status: active
corroborations: 1
---

# core.quotepath can defeat regression-pin detection in escape/detect.py

Git's default `core.quotepath=true` octal-escapes non-ASCII filenames in `git log`/`git diff` output. `src/escape/detect.py`'s regression-pin detection parses raw git output without unquoting these paths, so a regression test added/removed at a non-ASCII path can go undetected. Identified during review of PR #10521 (issue #10499); explicitly acknowledged and scoped out of that PR's plan rather than fixed — no follow-up issue filed yet as of 2026-07-25. **Why:** silently mis-parsed paths mean a regression pin can be missed for any repo with non-ASCII test filenames, with no visible error.
