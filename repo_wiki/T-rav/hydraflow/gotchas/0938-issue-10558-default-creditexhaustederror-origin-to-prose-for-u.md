---
id: 0938
topic: gotchas
source_issue: 10558
source_phase: plan
created_at: 2026-07-25T23:16:50.588358+00:00
status: active
corroborations: 1
---

# Default CreditExhaustedError.origin to "prose" for untagged raise sites

New/legacy `CreditExhaustedError` raise sites that don't explicitly set `origin` must default to `CREDIT_ORIGIN_PROSE`, not `cli`.
- Example: any raise in `src/runner_utils.py` or `src/adversarial_agent_runner.py` left unaudited keeps today's exact probe-gated behavior instead of silently becoming probe-exempt.
**Why:** an unclassified site defaulting to `cli` would bypass the probe gate and reopen the #9895/#9807 false-positive-pause bug; defaulting to `prose` is the fail-safe direction.
