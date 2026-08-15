---
id: 0329
topic: architecture
source_issue: 11161
source_phase: plan
created_at: 2026-08-14T18:36:34.319415+00:00
status: active
corroborations: 1
---

# Regression encodings are reachable via git grep, not added_paths

When a detecting commit is docs-only (`added_paths` has no test files), the regression encoding is still reachable through `auto_diagnose.regression_hits`' `git grep` across the full repo history.

- Commit `9196f7403620` only adds `docs/architecture/jsonl_ledger.likec4`, but `tests/regressions/test_issue_10498.py` contains the encoding.
- `diagnose(record)` needs no signature change — the `git grep` path finds it regardless.

**Why:** Relying on `added_paths` alone would miss encodings in pre-existing files, causing false HITL issues.
