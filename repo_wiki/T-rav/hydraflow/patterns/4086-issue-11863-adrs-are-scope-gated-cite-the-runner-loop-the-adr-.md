---
id: 4086
topic: patterns
source_issue: 11863
source_phase: plan
created_at: 2026-09-01T06:14:33.638624+00:00
status: active
corroborations: 1
---

# ADRs are scope-gated; cite the runner/loop the ADR governs

When planning work, decide whether an ADR applies by checking whether the construct the ADR governs is actually being added. For `ADR-0049`, mark N/A when the work adds no new loop or spawning runner — `CharterLoopRunner` and siblings are reused.

**Why:** Over-applying an ADR to work outside its scope introduces unneeded governance overhead and false compliance flags.
