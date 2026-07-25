---
id: 0835
topic: gotchas
source_issue: 10499
source_phase: plan
created_at: 2026-07-25T01:53:00.854299+00:00
status: active
corroborations: 1
---

# str.splitlines() breaks control-char sentinels in git-adapter parsing

Never delimit parsed git output with a marker containing a character `str.splitlines()` treats as a line boundary (`\x1c`, `\x1d`, `\x1e`, `\x85`, U+2028, U+2029) — the marker itself gets shattered mid-token before `startswith()` ever sees it. `src/escape/detect.py`'s `_SHA_MARKER = "\x1eESCSHA\x1e"` hit this: `_added_paths_for_range` always returned `{}` because `out.splitlines()` split on the `\x1e` inside the marker. Fix: use an ASCII-safe sentinel and split explicitly on `"\n"` only, never `.splitlines()`, when parsing self-emitted git markers.
**Why:** a silently-empty parse result degrades classification instead of raising, so the bug hides for months as spurious low-confidence noise.
