---
id: 1401
topic: gotchas
source_issue: 11247
source_phase: plan
created_at: 2026-08-15T20:03:13.665702+00:00
status: active
corroborations: 1
---

# FakeGitHub `_run_gh` must project rows by `--json` field names

When `--json` is passed to `gh issue list`/`pr list` in `FakeGitHub._run_gh`, emit exactly the named fields in gh wire shape (`labels` as `[{"name": ...}]`), not a hardcoded set. Absent `--json` keeps the legacy field set for back-compat. Unknown `--json` fields degrade to `null` with one logged warning, never raise.

Example: `gh issue list --state all --json number,state,labels,createdAt,closedAt` must return all five keys per row.

**Why:** Callers like `_make_fitness_issue_fetcher` request specific fields; omitting `state`/`createdAt`/`closedAt` raises `KeyError` on the first row.
