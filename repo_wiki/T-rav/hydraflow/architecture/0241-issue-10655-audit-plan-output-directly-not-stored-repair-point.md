---
id: 0241
topic: architecture
source_issue: 10655
source_phase: plan
created_at: 2026-07-26T16:28:39.816299+00:00
status: active
corroborations: 1
---

# Audit plan output directly, not stored repair pointers

The lesson-coverage auditor (`src/wiki_lesson_coverage.py`, CLI `scripts/audit_wiki_lesson_coverage.py`) consumes `plan_topic_repair`'s `left_on_primary` set at call time rather than reading stored supersession pointers from `repo_wiki/`. This means the auditor works both before and after #10572's repair is applied to live data.
- The planner owns "what a round is"; auditors must not re-derive it.
**Why:** Stored pointers reflect post-repair state and hide the gap the audit is designed to find; plan output captures the predecessor set at decision time.
