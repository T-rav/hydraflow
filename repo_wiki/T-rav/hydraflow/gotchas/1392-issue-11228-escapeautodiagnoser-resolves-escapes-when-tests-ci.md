---
id: 1392
topic: gotchas
source_issue: 11228
source_phase: plan
created_at: 2026-08-15T07:17:21.034762+00:00
status: active
corroborations: 1
---

# EscapeAutoDiagnoser resolves escapes when tests cite the source bug

Per ADR-0115, `EscapeAutoDiagnoser` reclassifies an escape from `encoded_as: none` to `regression-test` once a test file under `tests/` cites the bug ID.

- The detector scans `tests/` via `regression_hits` (word-boundary `git grep`)
- On the next `EscapeLedgerLoop` tick (#10577), the issue auto-closes
- Fallback if auto-diagnosis stalls: `make escape-resolve ARGS="bug-issue:<hash> --encoded-as regression-test"`

**Why:** Without a test citing the bug, the escape remains unresolved and the aging surface keeps re-firing indefinitely.
