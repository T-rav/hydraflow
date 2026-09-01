---
id: 1561
topic: gotchas
source_issue: 11969
source_phase: plan
created_at: 2026-09-01T11:15:55.080399+00:00
status: active
corroborations: 1
---

# MemoryBacklogLoop is its own sweeper — no parallel repair tool

When `MemoryBacklogLoop` gains a self-healing pass (e.g. `_revalidate_pins`), do not also ship a one-off repair script for the same defect. The loop IS the sweeper; in-tree data is reset directly.

Example: the 20 pre-history pins (#25–#44) in `docs/wiki/memory-feedback/*.md` are reset to `status: pending`, `issue: null` as a data delta, not via a tool.

**Why:** A parallel repair tool duplicates the loop's logic and rots the moment the loop changes — exactly the duplication this mirror warns about.
