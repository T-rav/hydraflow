---
id: 1390
topic: gotchas
source_issue: 11228
source_phase: plan
created_at: 2026-08-15T07:17:21.034707+00:00
status: active
corroborations: 1
---

# regression_hits uses -w word boundary; bug IDs need standalone #prefix

When encoding an escape via `auto_diagnose.regression_hits`, the literal bug ID must appear as a standalone token like `#10494`, not embedded in an identifier.

- The detector runs `git grep -l -F -I -w -e 10494 HEAD -- tests/`
- `-w` means `test_issue_10494` and `_10494` do **not** match
- A test file named `test_issue_11228.py` must still contain a bare `#10494` comment or string

**Why:** Without the standalone token, the escape stays at `encoded_as: none` and `EscapeAutoDiagnoser` never fires, so the issue never auto-closes.
