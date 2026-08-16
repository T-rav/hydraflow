---
id: 3241
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:47.311518+00:00
status: active
corroborations: 1
supersedes: 3108
---

# Wiki repair CLI: dry-run default, --apply to write, --only-id to scope

`scripts/repair_wiki_supersession.py` defaults to dry-run; `--apply` writes, `--only-id` scopes writes to a single entry (frontmatter-only), and topics come via `discover_topics` — no hardcoded lists.

Example: `--restore-orphans` without `--apply` previews which of the 471 `left_on_primary` predecessors would be restored. See also: [patterns] — Orphan-fold classifier: title-token overlap + supersedes count.

**Why:** Prevents accidental corpus-wide writes during exploratory repair classification of `left_on_primary` predecessors.
