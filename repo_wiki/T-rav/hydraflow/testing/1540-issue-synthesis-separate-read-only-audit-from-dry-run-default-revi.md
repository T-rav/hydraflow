---
id: 1540
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.863574+00:00
status: active
corroborations: 1
supersedes: 1453
---

# Separate read-only audit from dry-run-default revive tool

Keep wiki audit and wiki repair as separate binaries with distinct safety profiles.

- `scripts/audit_wiki_lesson_coverage.py` is read-only: `repo_wiki/` is git-tracked, `git status --porcelain` stays empty after a run, and no `--apply` flag exists.
- `scripts/revive_wiki_lessons.py` is dry-run by default, frontmatter-only, and applies human-reviewed verdicts from `lesson-coverage-verdicts.json`.

**Why:** Merging read and write paths makes every audit run a potential corpus mutation; separating them lets the audit run in CI without write risk.
