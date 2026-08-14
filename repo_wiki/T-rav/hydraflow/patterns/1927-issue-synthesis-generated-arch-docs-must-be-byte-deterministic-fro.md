---
id: 1927
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:27.034326+00:00
status: active
corroborations: 1
supersedes: 1829
---

# Generated arch docs must be byte-deterministic from source

Generated markdown under `docs/arch/generated/` (e.g. `setpoint-density.md`) must be byte-identical when re-rendered from the same corpus.

Example: Register the generator in `src/arch/runner.py` with `trends=None` for the per-ADR table form; passing trend rows additionally renders the monthly table. Rendering twice with `trends=None` over one corpus must produce identical bytes.

**Why:** Non-deterministic output makes arch-regen and `DiagramLoop` fight over the committed file.
