---
id: 2862
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:52.063000+00:00
status: active
corroborations: 1
supersedes: 2733
---

# Set horizon caps with ~50% headroom over current span

When adding a horizon cap to `GRANDFATHERED_SCHEDULE_LOG` in `src/prompt_fitness.py`, leave roughly 50% headroom above today's real span.

Example: `GRANDFATHERED_MAX_HORIZON_DAYS = 92` against a current 62-day span.

**Why:** A cap that blocks all future legitimate extensions is a self-removing guard; headroom keeps the ratchet enforceable.
