---
id: 1465
topic: gotchas
source_issue: 11354
source_phase: plan
created_at: 2026-08-16T15:20:51.560165+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Route GET fetchers through fetchJsonInto for health tracking in HydraFlowContext

Use the provider-local `fetchJsonInto(key, url, toAction)` wrapper to centralize all GET-then-dispatch fetchers in `HydraFlowContext.jsx`.

- Rejects on `!res.ok` (carrying status)
- Dispatches the data action **only** on success
- Always dispatches `FETCH_HEALTH`
- Never clears `pipelineIssues` on failure (last-good render is the point)

**Why:** Avoids duplicating health-tracking logic across 10+ fetchers and ensures consistent degraded-state behavior across every poll.
