---
id: 1470
topic: patterns
source_issue: 10917
source_phase: plan
created_at: 2026-07-31T16:16:35.877475+00:00
status: superseded
corroborations: 1
superseded_by: 1554
---

# Generated arch docs must be byte-deterministic from source

Generated markdown under `docs/arch/generated/` (e.g. `setpoint-density.md`) must be byte-identical when re-rendered from the same corpus. Register the generator in `src/arch/runner.py` with `trends=None` for the per-ADR table form; passing trend rows additionally renders the monthly table. Rendering twice with `trends=None` over one corpus must produce identical bytes. **Why:** Non-deterministic output makes arch-regen and `DiagramLoop` fight over the committed file.
