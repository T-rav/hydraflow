---
id: 2305
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.981529+00:00
status: superseded
corroborations: 1
supersedes: 2160
superseded_by: 2495
---

# Separate read-only audit from dry-run-default revive tool

Keep wiki audit and wiki repair as separate binaries with distinct safety profiles.

Example: `scripts/audit_wiki_lesson_coverage.py` is read-only (git status stays empty, no `--apply`); `scripts/revive_wiki_lessons.py` is dry-run by default, frontmatter-only, and applies human-reviewed verdicts from `lesson-coverage-verdicts.json`. See also: testing — repo_wiki auditors must be read-only; never add --apply.

**Why:** Merging read and write paths makes every audit run a potential corpus mutation; separating them lets the audit run in CI without write risk.
