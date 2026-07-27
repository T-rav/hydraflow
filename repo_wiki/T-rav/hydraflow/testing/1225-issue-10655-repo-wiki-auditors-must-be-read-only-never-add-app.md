---
id: 1225
topic: testing
source_issue: 10655
source_phase: plan
created_at: 2026-07-26T16:28:39.816293+00:00
status: superseded
corroborations: 1
superseded_by: 1299
---

# repo_wiki/ auditors must be read-only; never add --apply

`repo_wiki/` is git-tracked. Auditor CLIs (e.g. `audit_wiki_lesson_coverage.py`) must have no write path — no `--apply`, no file mutation. Surface findings via stdout + optional `--json` artifact only. A passing run leaves `git status --porcelain repo_wiki/` empty.
- Suppressed buckets (`no_anchor`, not-live) are reported as counts, never silently dropped.
**Why:** Write paths in an auditor couple diagnostic tooling to mutation, making it impossible to dry-run safely against the live tree.
