---
id: 1452
topic: testing
source_issue: 10754
source_phase: plan
created_at: 2026-07-27T23:21:47.785762+00:00
status: superseded
corroborations: 1
superseded_by: 1536
---

# Repo wiki auditor scripts: read-only, no --apply, no MockWorld e2e

Repo wiki auditor scripts follow the `scripts/repair_wiki_supersession.py` precedent: read-only, stdout + optional `--json`, no `--apply` flag, no MockWorld scenario or sandbox e2e.

Example: `scripts/audit_wiki_lesson_coverage.py` consumes `plan_topic_repair` output at call time (never stored `superseded_by`), scans topic dirs dynamically, and reports suppressed buckets (`no_anchor`, `not_live`) as counts.

**Why:** Auditors inspect live state; adding a write path or stubbing the plan output defeats the purpose and risks silently mutating the corpus.
