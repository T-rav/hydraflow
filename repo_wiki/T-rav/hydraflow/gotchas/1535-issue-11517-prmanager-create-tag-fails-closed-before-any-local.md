---
id: 1535
topic: gotchas
source_issue: 11517
source_phase: plan
created_at: 2026-08-21T09:19:56.754288+00:00
status: active
corroborations: 1
---

# PRManager.create_tag fails closed before any local git tag exists

In `PRManager.create_tag` (`src/pr_manager.py`), any `git fetch origin <main_branch>` or `git rev-parse --verify` failure must `logger.warning` (literal format string) and `return False` BEFORE `git tag` executes. Order: dry-run short-circuit → fetch → rev-parse → tag resolved SHA → push.

**Why:** returning after tagging leaves an orphan local tag pointing at the wrong SHA even though the caller believed the release was skipped — the skip must leave no filesystem residue.
