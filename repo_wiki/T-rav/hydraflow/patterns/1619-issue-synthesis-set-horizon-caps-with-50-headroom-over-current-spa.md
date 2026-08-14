---
id: 1619
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T07:44:05.723737+00:00
status: superseded
corroborations: 1
supersedes: 1534
superseded_by: 1713
---

# Set horizon caps with ~50% headroom over current span

When adding a horizon cap to `GRANDFATHERED_SCHEDULE_LOG` in `src/prompt_fitness.py`, leave roughly 50% headroom above today's real span.

Example: `GRANDFATHERED_MAX_HORIZON_DAYS = 92` against a current 62-day span. Setting the cap at exactly today's span makes legitimate renegotiation impossible.

**Why:** A cap that blocks all future legitimate extensions is a self-removing guard; headroom keeps the ratchet enforceable.
