---
id: 1293
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.496558+00:00
status: superseded
corroborations: 1
supersedes: 1219
superseded_by: 1367
---

# Harvest claims from both body json:entry and frontmatter

In src/repo_wiki.py, `_load_tracked_active_entries` must read shipped claims (`fixed_in_pr`/`code_refs`) from both the body's `json:entry` block AND frontmatter fields — hand-authored tracked entries use either form interchangeably.

Example: a tracked entry with `fixed_in_pr` in frontmatter but no `json:entry` block must still surface its claim after promotion.

**Why:** Reading only one source silently drops claims written the other way; promotion must never erase a shipped assertion just because the source entry happened to use the format the loader wasn't checking.
