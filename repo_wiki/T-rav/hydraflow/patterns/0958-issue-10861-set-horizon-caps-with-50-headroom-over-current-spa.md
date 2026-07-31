---
id: 0958
topic: patterns
source_issue: 10861
source_phase: plan
created_at: 2026-07-31T01:46:44.758681+00:00
status: superseded
corroborations: 1
superseded_by: 1022
---

# Set horizon caps with ~50% headroom over current span

When adding a horizon cap to `GRANDFATHERED_SCHEDULE_LOG` in `src/prompt_fitness.py`, leave roughly a quarter of headroom above today's real span — e.g. `GRANDFATHERED_MAX_HORIZON_DAYS = 92` against a current 62-day span.

- Setting the cap at exactly today's span makes legitimate renegotiation impossible.
- Next debt-carrying PR will delete the cap rather than append a receipt.

**Why:** A cap that blocks all future legitimate extensions is a self-removing guard; headroom keeps the ratchet enforceable.
