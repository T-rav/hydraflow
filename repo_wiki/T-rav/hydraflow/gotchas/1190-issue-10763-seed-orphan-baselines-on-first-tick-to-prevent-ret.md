---
id: 1190
topic: gotchas
source_issue: 10763
source_phase: plan
created_at: 2026-07-28T00:17:34.080259+00:00
status: active
corroborations: 1
---

# Seed orphan baselines on first tick to prevent retro-filing storms

When adding orphan-detection to an existing corpus, persist a baseline of already-orphaned subjects on the first tick and file only newly-orphaned subjects thereafter. The baseline is seeded, not filed, so standing predecessors stay in the scope of the issue that owns them.

Example: `StateData.wiki_lesson_orphan_baseline` holds subject strings like `{slug}:lesson {topic}/{id}`. First tick after upgrade files zero lesson issues and populates the baseline from the existing 471 predecessors; only orphans appearing on later ticks fire `create_issue`.

**Why:** Without seeding, the first enabled tick floods `hydraflow-find` with hundreds of issues for pre-existing orphans.
