---
id: 1242
topic: gotchas
source_issue: 10899
source_phase: plan
created_at: 2026-07-31T11:25:57.702193+00:00
status: active
corroborations: 1
---

# FakeGitHub models GitHub workflow display name and file name as separate slots

GitHub exposes two distinct workflow identifiers: a display name (`.name` in API responses) and a file name (used in URL paths). `FakeGitHub.add_workflow_run` must accept both `workflow=` (display) and `workflow_file=` (file) slots. Derivation is forward-only: display → file via slugification, never reverse.

Example: `"RC Promotion Scenario"` → `rc-promotion-scenario.yml`; `"CI"` → `ci.yml`. A seed already ending `.yml`/`.yaml` is used as-is.

**Why:** Conflating the two identifiers produces consumers that pass in MockWorld but fail against live GitHub, because file-scoped reads (`list_runs_for_workflow`) match on file name while repo-wide reads (`list_workflow_runs`) project display name.
