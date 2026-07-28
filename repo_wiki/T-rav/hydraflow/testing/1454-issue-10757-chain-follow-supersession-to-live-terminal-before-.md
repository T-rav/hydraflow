---
id: 1454
topic: testing
source_issue: 10757
source_phase: plan
created_at: 2026-07-28T00:08:58.218712+00:00
status: superseded
corroborations: 1
superseded_by: 1541
---

# Chain-follow supersession to live terminal before scoring wiki lessons

Rule: When scoring a `left_on_primary` predecessor's lesson coverage, follow the full `superseded_by` chain to the live terminal entry before scoring — never score against the immediate successor.

In the live `repo_wiki/T-rav/hydraflow` corpus, 427 of 471 `left_on_primary` immediate targets are themselves superseded. Scoring against the intermediate would bucket ~90% of edges as `not_live` and produce a vacuously clean report.

**Why:** Scoring a dead intermediate masks orphaned lessons instead of surfacing them, defeating the entire purpose of `src/wiki_lesson_coverage.py`.
