---
id: 0424
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:37:01.325036+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415
---

# docs/arch/generated/* is a make arch-regen artifact — never hand-edit

Regenerate `docs/arch/generated/*` via `make arch-regen` rather than hand-editing the generated Markdown/Mermaid, e.g. after removing a loop like `PrRedRepairLoop` from `functional_areas.yml`'s quality_gates group. Example: hand-editing or forgetting to regen reddens the `arch-regen.yml` CI check. **Why:** the generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
