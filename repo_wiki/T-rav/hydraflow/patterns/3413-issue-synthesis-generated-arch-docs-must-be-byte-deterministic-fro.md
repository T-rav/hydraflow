---
id: 3413
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.901844+00:00
status: superseded
corroborations: 1
supersedes: 3276
superseded_by: 3560
---

# Generated arch docs must be byte-deterministic from source

Generated markdown under `docs/arch/generated/` (e.g. `setpoint-density.md`) must be byte-identical when re-rendered from the same corpus.

Example: Register the generator in `src/arch/runner.py` with `trends=None` for the per-ADR table form; passing trend rows additionally renders the monthly table. Rendering twice with `trends=None` over one corpus must produce identical bytes.

**Why:** Non-deterministic output makes arch-regen and `DiagramLoop` fight over the committed file.
