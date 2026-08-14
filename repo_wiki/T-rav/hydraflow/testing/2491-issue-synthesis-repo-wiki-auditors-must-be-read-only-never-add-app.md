---
id: 2491
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.362565+00:00
status: active
corroborations: 1
supersedes: 2301
---

# repo_wiki auditors must be read-only; never add --apply

Repo wiki auditor scripts must be read-only — no `--apply` flag, no file mutation, stdout + optional `--json` only. A passing run leaves `git status --porcelain repo_wiki/` empty.

Example: `scripts/audit_wiki_lesson_coverage.py` consumes `plan_topic_repair` output, scans topic dirs dynamically, reports suppressed buckets (`no_anchor`, `not_live`) as counts.

**Why:** Write paths in an auditor couple diagnostic tooling to mutation, making it impossible to dry-run safely against the live git-tracked corpus.
