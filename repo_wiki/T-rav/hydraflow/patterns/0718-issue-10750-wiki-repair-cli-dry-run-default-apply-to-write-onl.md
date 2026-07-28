---
id: 0718
topic: patterns
source_issue: 10750
source_phase: plan
created_at: 2026-07-27T22:53:53.519967+00:00
status: active
corroborations: 1
---

# Wiki repair CLI: dry-run default, --apply to write, --only-id to scope

`scripts/repair_wiki_supersession.py` exposes `--restore-orphans` (dry-run default) requiring `--apply` to write; `--only-id` restricts writes to a single entry (frontmatter-only). Topics come via `discover_topics` — no hardcoded lists. **Why:** Prevents accidental corpus-wide writes during exploratory repair classification of the 471 `left_on_primary` predecessors.
