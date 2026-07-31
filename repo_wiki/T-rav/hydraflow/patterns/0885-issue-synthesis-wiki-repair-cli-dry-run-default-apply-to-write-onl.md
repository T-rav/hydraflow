---
id: 0885
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.655414+00:00
status: superseded
corroborations: 1
supersedes: 0830
superseded_by: 0943
---

# Wiki repair CLI: dry-run default, --apply to write, --only-id to scope

`scripts/repair_wiki_supersession.py` exposes `--restore-orphans` (dry-run default) requiring `--apply` to write; `--only-id` restricts writes to a single entry (frontmatter-only). Topics come via `discover_topics` — no hardcoded lists.

**Why:** Prevents accidental corpus-wide writes during exploratory repair classification of the 471 `left_on_primary` predecessors.
