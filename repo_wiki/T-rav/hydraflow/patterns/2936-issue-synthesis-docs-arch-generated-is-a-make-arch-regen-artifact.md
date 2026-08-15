---
id: 2936
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T20:34:47.607002+00:00
status: active
corroborations: 1
supersedes: 2809
---

# docs/arch/generated/* is a make arch-regen artifact

Regenerate `docs/arch/generated/*` via `make arch-regen` rather than hand-editing the generated Markdown/Mermaid.

Example: After removing a loop like `PrRedRepairLoop` from `functional_areas.yml`, run `make arch-regen`. Hand-editing reddens the `arch-regen.yml` CI check. See also: [patterns] — ADR citations must be symbol-qualified, not bare file paths.

**Why:** Generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
