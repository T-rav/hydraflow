---
id: 3605
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:23.324210+00:00
status: superseded
corroborations: 1
supersedes: 3458
superseded_by: 3750
---

# Redrive TTL > branch GC stale days: accept overlap, don't gate

Do not add an extra gate when `auto_agent_redrive_ttl_days` (5) exceeds `branch_gc_stale_days` (3). A truth comment can land mid-redrive window — this is accepted.

Rely on existing safeguards: `find_open_pr_for_branch` skips in-flight PRs; truth comments are deduped once per branch; comments are informational only (no label/close side effects). State this acceptance in the PR body.

**Why:** Adding a redrive-awareness gate would couple two independent TTLs and add complexity for no functional benefit, since the comment has no side effects that could interfere with an active redrive.
