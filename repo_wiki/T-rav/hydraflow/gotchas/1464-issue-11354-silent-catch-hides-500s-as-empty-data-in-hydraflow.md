---
id: 1464
topic: gotchas
source_issue: 11354
source_phase: plan
created_at: 2026-08-16T15:20:51.560122+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Silent .catch(() => {}) hides 500s as empty data in HydraFlowContext fetchers

Never swallow fetch errors in `HydraFlowContext.jsx` GET-then-dispatch chains without checking `res.ok`. The existing pattern (e.g., `fetchPipeline`) ends in `.catch(() => {})` and skips `res.ok`, so a 500 on `/api/pipeline` renders as an empty board with no degradation signal.

Affected fetchers include `fetchPipeline`, `fetchPipelineStats`, `fetchGithubMetrics`, `fetchMetricsHistory`, `fetchLoopFitness`, `fetchAdrConformance`, `fetchEpics`, `fetchSessions`, `fetchLifetimeStats`, `fetchHitlItems`, `fetchTrackedReports`, plus inline `/api/prs`, `/api/queue`, `/api/metrics`, `/api/system/workers` polls. POST mutations and WS backfill are exempt.

**Why:** Operators see a confidently-empty UI with no indication that the backend is failing.
