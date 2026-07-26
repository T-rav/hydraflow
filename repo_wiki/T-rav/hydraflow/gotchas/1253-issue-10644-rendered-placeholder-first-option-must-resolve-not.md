---
id: 1253
topic: gotchas
source_issue: 10644
source_phase: plan
created_at: 2026-07-26T12:01:31.012801+00:00
status: active
corroborations: 1
---

# Rendered placeholder first-option must resolve, not strand

When `_render_finding` emits a `<a|b|c>` choice placeholder for operator substitution, the first option must be one that closes the finding — not the current failing state.

- Correct: `--confidence <high|medium|low>` — operator defaults to `high`, which bumps off `low`.
- Wrong: `--confidence <low|medium|high>` — operator defaults to `low`, finding still strands.

`tests/regressions/test_issue_10644.py` substitutes the first option verbatim and asserts `_reconcile_surfaced_issues()` closes the issue.

**Why:** Operators collapse `<a|b|c>` to the first option; if that option reproduces the failure state, the finding cannot close and the regression test fails confusingly.
