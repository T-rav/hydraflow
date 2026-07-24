---
id: 0396
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.609724+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
---

# docs/arch/generated/* is a make arch-regen artifact — never hand-edit

After removing a loop (e.g. `PrRedRepairLoop` from `functional_areas.yml`'s quality_gates group), regenerate `docs/arch/generated/*` via `make arch-regen` rather than editing the generated Markdown/Mermaid directly.

Example: hand-editing or forgetting to regen reddens the `arch-regen.yml` CI check.

**Why:** the generated docs are a build artifact of the live loop registry, port map, and functional-area map — manual edits silently drift from source on the next real regen.
