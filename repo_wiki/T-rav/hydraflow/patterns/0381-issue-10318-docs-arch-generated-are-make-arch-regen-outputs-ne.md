---
id: 0381
topic: patterns
source_issue: 10318
source_phase: plan
created_at: 2026-07-24T04:19:41.513821+00:00
status: superseded
corroborations: 1
superseded_by: 0388
---

# `docs/arch/generated/*` are `make arch-regen` outputs — never hand-edit

After removing a loop (e.g. `PrRedRepairLoop` from `functional_areas.yml`'s quality_gates group), regenerate `docs/arch/generated/*` via `make arch-regen` rather than editing the generated Markdown/Mermaid directly. Hand-editing or forgetting to regen reddens the `arch-regen.yml` CI check.

**Why:** the generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
