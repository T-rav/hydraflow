---
id: 4069
topic: patterns
source_issue: 11424
source_phase: review
created_at: 2026-08-18T09:01:27.985852+00:00
status: active
corroborations: 1
---

# Check PR mergeability before reviewing diff content

Before reviewing a PR's code content, check `gh pr view <n> --json mergeable,mergeStateStatus` and diff touched functions against the current base branch. HydraFlow folds sibling sites into one class-fix per CLAUDE.md's "sweep all sites, file ONE issue" rule, so a concurrently-filed PR can be fully superseded before it's opened.

Example: PR #11448 targeted `tests/scenarios/catalog/loop_registrations.py` but was CONFLICTING because PR #11428 (issue #11416) had already fixed the same builders on `staging`.

**Why:** Reviewing only the diff in isolation looks clean but ships incompatible conventions or duplicate files that regress an already-shipped, more general fix.
