---
id: 0847
topic: gotchas
source_issue: 10499
source_phase: review
created_at: 2026-07-25T06:08:03.278840+00:00
status: stale
corroborations: 1
stale_reason: source issue #10499 closed
---

# core.quotepath can defeat regression-pin detection in escape/detect.py

Git's default `core.quotepath=true` octal-escapes non-ASCII filenames in `git log`/`git diff` output, wrapping the whole path in literal quotes — which defeats a `startswith()` match against the raw path. Identified during review of PR #10521 (issue #10499) as initially unaddressed; fixed in the same PR by passing `-c core.quotepath=false` to the `git log` invocations in both `escape.detect._added_paths_for_range` and `audit.detect._changed_paths_for_range` (twin modules, same defect class), with non-ASCII-path regression coverage in `tests/regressions/test_issue_10499.py`. **Why:** silently mis-parsed paths mean a regression pin can be missed for any repo with non-ASCII test filenames, with no visible error — worth remembering as a general git-log-adapter gotcha even though this instance is now closed.
