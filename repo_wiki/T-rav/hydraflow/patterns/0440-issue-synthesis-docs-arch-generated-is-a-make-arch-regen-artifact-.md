---
id: 0440
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:06:34.704052+00:00
status: superseded
corroborations: 1
supersedes: 0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431
superseded_by: 0447
---

# docs/arch/generated/* is a make arch-regen artifact — never hand-edit

Regenerate `docs/arch/generated/*` via `make arch-regen` rather than hand-editing the generated Markdown/Mermaid, e.g. after removing a loop like `PrRedRepairLoop` from `functional_areas.yml`'s quality_gates group. Example: hand-editing or forgetting to regen reddens the `arch-regen.yml` CI check. **Why:** the generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
