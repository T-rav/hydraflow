---
id: 0178
topic: architecture
source_issue: 10434
source_phase: plan
created_at: 2026-07-24T10:19:32.942809+00:00
status: active
corroborations: 1
---

# Doc-only ADR citation fixes skip MockWorld/e2e layers by design

A citation-granularity fix to a `docs/adr/*.md` file with no `src/` code change only needs a unit-level regression test exercising `compute_drift` — no MockWorld scenario or sandbox e2e is required, since there's no phase-crossing or runtime behavior involved (per `docs/standards/testing/README.md`'s pyramid, this is a legitimate case where a layer is genuinely not applicable, not skipped out of laziness).

**Why:** clarifies when the full three-layer test pyramid doesn't apply — doc/metadata-only changes to the ADR drift engine's input, not its logic.
