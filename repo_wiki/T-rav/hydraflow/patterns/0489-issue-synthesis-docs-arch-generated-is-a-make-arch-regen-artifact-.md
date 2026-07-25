---
id: 0489
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:09:57.506866+00:00
status: active
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
---

# docs/arch/generated/* is a make arch-regen artifact — never hand-edit

Regenerate `docs/arch/generated/*` via `make arch-regen` rather than hand-editing the generated Markdown/Mermaid, e.g. after removing a loop like `PrRedRepairLoop` from `functional_areas.yml`'s quality_gates group.

Example: hand-editing or forgetting to regen reddens the `arch-regen.yml` CI check.

**Why:** the generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
