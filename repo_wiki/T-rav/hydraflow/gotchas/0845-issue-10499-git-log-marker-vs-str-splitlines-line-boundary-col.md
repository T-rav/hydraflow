---
id: 0845
topic: gotchas
source_issue: 10499
source_phase: review
created_at: 2026-07-25T06:08:03.278794+00:00
status: active
corroborations: 1
---

# Git log marker vs str.splitlines() line-boundary collision

`_SHA_MARKER` sentinels prefixed to `git log --pretty=format` lines must not use `\x1e` (ASCII Record Separator) — `str.splitlines()` treats `\x1e` as its own line boundary, so a marker line silently splits mid-token and `line.startswith(_SHA_MARKER)` never matches. `src/escape/detect.py:42` and `src/audit/detect.py:24` both had this bug (PR #10521, issue #10499); the fix switches the marker to `\x01` and parses with `output.split("\n")` instead of `.splitlines()`, matching git's actual line termination. **Why:** `str.splitlines()` splits on the full Unicode line-boundary set, not just `\n` — a sentinel drawn from that set defeats prefix matching on real repo output.
