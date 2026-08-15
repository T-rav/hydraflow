---
id: 2544
topic: patterns
source_issue: 11218
source_phase: plan
created_at: 2026-08-15T06:29:26.164426+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Drop stashes highest-index-first to survive renumbering

When pruning stale stashes in `scripts/run-factory-isolated.sh`, iterate `git stash list` entries from highest index to lowest. `git stash drop stash@{N}` renumbers all higher indices down by one, so a naive ascending loop skips entries and drops the wrong stashes.

- Parse `git stash list --format='%gd|%ct|%gs'` for selector, committer timestamp, and subject.
- Drop in descending index order; age comes from `%ct`, not reflog prose.

**Why:** Ascending drop silently prunes the wrong stashes, leaving stale entries behind while discarding recent work.
