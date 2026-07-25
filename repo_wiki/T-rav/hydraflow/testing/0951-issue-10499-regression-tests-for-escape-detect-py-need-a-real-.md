---
id: 0951
topic: testing
source_issue: 10499
source_phase: plan
created_at: 2026-07-25T01:53:00.854342+00:00
status: active
corroborations: 1
---

# Regression tests for escape/detect.py need a real temp git repo, not synthetic added_paths

`tests/test_escape_ledger.py` feeds `added_paths` to `_classify` synthetically, which cannot catch bugs in the git-adapter parse layer (`_added_paths_for_range`, `commits_for_range`) upstream of classification. `tests/regressions/test_issue_10499.py` instead drives `commits_for_range` against a real temp git repo whose commit adds `tests/regressions/x.py`, asserting `added_paths` is non-empty and correctly attributed per-commit (not merged across a multi-commit range).
**Why:** synthetic-input unit tests exercise `_classify` correctly but leave the marker-parsing path (`_SHA_MARKER`, `out.splitlines()`) completely uncovered — exactly how this escaped to production.
