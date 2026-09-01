---
id: 2808
topic: testing
source_issue: 11948
source_phase: plan
created_at: 2026-09-01T10:57:18.007878+00:00
status: active
corroborations: 1
---

# Tests parametrise policy globs by reference from loaded PolicyEntry

Per `docs/standards/parametrised_guards/`, tests read path globs from the loaded `PolicyEntry` rather than re-declaring a literal list. Reuse `ConfigFactory`, `install_repo_merge_policy`, and `STRICT_MERGE_POLICY` from `tests/helpers.py` — do not re-declare them.

MockWorld scenario tests use Pattern B (`PostMergeHandler` + `FakeGitHub` + `install_repo_merge_policy`) with no real git/gh/subprocess. Regression tests include a mutation kill (deleting the author role must redden the test).

**Why:** Prevents drift between test expectations and the shipped `policy.yaml`.
