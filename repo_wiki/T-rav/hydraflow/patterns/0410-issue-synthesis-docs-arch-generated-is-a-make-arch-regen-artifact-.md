---
id: 0410
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:02:15.947168+00:00
status: active
corroborations: 1
supersedes: 0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# docs/arch/generated/* is a make arch-regen artifact — never hand-edit

Regenerate `docs/arch/generated/*` via `make arch-regen` rather than hand-editing the generated Markdown/Mermaid, e.g. after removing a loop like `PrRedRepairLoop` from `functional_areas.yml`'s quality_gates group. Example: hand-editing or forgetting to regen reddens the `arch-regen.yml` CI check. **Why:** the generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
