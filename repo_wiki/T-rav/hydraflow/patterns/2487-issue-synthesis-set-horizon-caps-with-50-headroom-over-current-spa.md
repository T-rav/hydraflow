---
id: 2487
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T06:55:23.664563+00:00
status: superseded
corroborations: 1
supersedes: 2367
superseded_by: 2610
---

# Set horizon caps with ~50% headroom over current span

When adding a horizon cap to `GRANDFATHERED_SCHEDULE_LOG` in `src/prompt_fitness.py`, leave roughly 50% headroom above today's real span.

Example: `GRANDFATHERED_MAX_HORIZON_DAYS = 92` against a current 62-day span.

**Why:** A cap that blocks all future legitimate extensions is a self-removing guard; headroom keeps the ratchet enforceable.
