---
id: 1536
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.855578+00:00
status: active
corroborations: 1
supersedes: 1448,1452
---

# repo_wiki/ auditors: read-only, no --apply, no MockWorld e2e

Repo wiki auditor scripts follow the `scripts/repair_wiki_supersession.py` precedent: read-only, stdout + optional `--json`, no `--apply` flag, no MockWorld scenario or sandbox e2e. `repo_wiki/` is git-tracked; a passing run leaves `git status --porcelain repo_wiki/` empty.

Example: `scripts/audit_wiki_lesson_coverage.py` consumes `plan_topic_repair` output at call time (never stored `superseded_by`), scans topic dirs dynamically, and reports suppressed buckets (`no_anchor`, `not_live`) as counts.

**Why:** Auditors inspect live state; adding a write path or stubbing the plan output defeats the purpose and risks silently mutating the corpus.
