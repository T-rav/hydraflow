---
id: 0969
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:11:10.500418+00:00
status: active
corroborations: 1
supersedes: 0905
---

# docs/arch/generated/* is a make arch-regen artifact

Regenerate `docs/arch/generated/*` via `make arch-regen` rather than hand-editing the generated Markdown/Mermaid.

Example: After removing a loop like `PrRedRepairLoop` from `functional_areas.yml`'s quality_gates group, run `make arch-regen`. Hand-editing reddens the `arch-regen.yml` CI check. See also: patterns — ADR citations must be symbol-qualified.

**Why:** Generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
