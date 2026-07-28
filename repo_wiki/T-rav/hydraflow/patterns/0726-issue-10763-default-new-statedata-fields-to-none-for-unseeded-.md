---
id: 0726
topic: patterns
source_issue: 10763
source_phase: plan
created_at: 2026-07-28T00:17:34.080275+00:00
status: active
corroborations: 1
---

# Default new StateData fields to None for unseeded semantics

New optional `StateData` fields that gate first-run behavior must default to `None`, not `[]` or `{}`. `None` signals "unseeded" (trigger first-run seeding); an empty collection signals "seeded with nothing" (skip seeding).

Example: `StateData.wiki_lesson_orphan_baseline: list[str] | None = None`. A pre-change state file deserializes the missing field as `None`, so the first tick seeds rather than treating the corpus as already-empty.

**Why:** An `[]` default would be indistinguishable from "seeded and found nothing," silently skipping the baseline seed and causing a retro-filing storm on the next tick.
