---
id: 0724
topic: patterns
source_issue: 10753
source_phase: plan
created_at: 2026-07-27T23:48:50.234485+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Wiki orphan restore is frontmatter-only, idempotent, dry-run default

Restore orphaned wiki predecessors by touching only three frontmatter keys: set `status: active`, drop `superseded_by`, prune the predecessor id from the target's `supersedes`. Bodies stay untouched.

- Second apply must write zero files (idempotency).
- Default invocation is dry-run; `--apply` to write.
- `git diff` on `repo_wiki/` touches only those three keys.

**Why:** Frontmatter-only deltas are mechanical, reviewable via `git diff --stat`, and avoid corrupting lesson bodies that may have diverged since the fold.
