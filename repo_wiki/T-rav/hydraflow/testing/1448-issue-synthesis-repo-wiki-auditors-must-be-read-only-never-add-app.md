---
id: 1448
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T00:21:29.183714+00:00
status: superseded
corroborations: 1
supersedes: 1373
superseded_by: 1536
---

# repo_wiki/ auditors must be read-only; never add --apply

`repo_wiki/` is git-tracked. Auditor CLIs (e.g. `audit_wiki_lesson_coverage.py`) must have no write path — no `--apply`, no file mutation. Surface findings via stdout + optional `--json` artifact only. A passing run leaves `git status --porcelain repo_wiki/` empty.

Example: suppressed buckets (`no_anchor`, not-live) are reported as counts, never silently dropped.

**Why:** Write paths in an auditor couple diagnostic tooling to mutation, making it impossible to dry-run safely against the live tree.
