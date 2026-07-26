---
id: 0507
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:10:56.105125+00:00
status: superseded
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
superseded_by: 0523
---

# docs/arch/generated/* is a make arch-regen artifact — never hand-edit

Regenerate `docs/arch/generated/*` via `make arch-regen` rather than hand-editing the generated Markdown/Mermaid, e.g. after removing a loop like `PrRedRepairLoop` from `functional_areas.yml`'s quality_gates group.

Example: hand-editing or forgetting to regen reddens the `arch-regen.yml` CI check.

**Why:** the generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
