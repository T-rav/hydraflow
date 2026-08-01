---
id: 2306
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.984200+00:00
status: active
corroborations: 1
supersedes: 2161
---

# Chain-follow supersession to live terminal before scoring

When scoring a `left_on_primary` predecessor's lesson coverage, follow the full `superseded_by` chain to the live terminal entry before scoring — never score against the immediate successor.

Example: in the live `repo_wiki/T-rav/hydraflow` corpus, 427 of 471 `left_on_primary` immediate targets are themselves superseded.

**Why:** Scoring a dead intermediate masks orphaned lessons instead of surfacing them, defeating the entire purpose of `src/wiki_lesson_coverage.py`.
