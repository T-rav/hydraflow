---
id: 1151
topic: testing
source_issue: 10590
source_phase: plan
created_at: 2026-07-26T04:12:39.569026+00:00
status: superseded
corroborations: 1
superseded_by: 1154
---

# Harvest claims from both body json:entry blocks and frontmatter, never just one

In `src/repo_wiki.py`, `_load_tracked_active_entries` must read shipped claims (`fixed_in_pr`/`code_refs`) from both the body's `json:entry` block AND frontmatter fields — hand-authored tracked entries use either form interchangeably. Reading only one source silently drops claims written the other way.
**Why:** promotion must never erase a shipped assertion just because the source entry happened to use the format the loader wasn't checking.
