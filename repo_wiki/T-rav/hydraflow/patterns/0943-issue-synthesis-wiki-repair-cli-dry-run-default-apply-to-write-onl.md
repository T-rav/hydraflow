---
id: 0943
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:33:17.964482+00:00
status: active
corroborations: 1
supersedes: 0885
---

# Wiki repair CLI: dry-run default, --apply to write, --only-id to scope

`scripts/repair_wiki_supersession.py` defaults to dry-run; `--apply` writes, `--only-id` scopes writes to a single entry (frontmatter-only), and topics come via `discover_topics` — no hardcoded lists.

Example: `--restore-orphans` without `--apply` previews which of the 471 `left_on_primary` predecessors would be restored.

**Why:** Prevents accidental corpus-wide writes during exploratory repair classification of `left_on_primary` predecessors.
