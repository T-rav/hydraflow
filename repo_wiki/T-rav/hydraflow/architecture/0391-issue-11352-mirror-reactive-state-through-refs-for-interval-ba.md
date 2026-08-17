---
id: 0391
topic: architecture
source_issue: 11352
source_phase: plan
created_at: 2026-08-16T14:31:03.716344+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Mirror reactive state through refs for interval-based effects in HydraFlowContext

When a `useEffect` sets up a `setInterval` that needs to read live reducer state (`lastEventAt`, `pipelinePollerLastRun`, `pipelineResyncing`), read those values through a ref mirror — never put them in the effect's dep array.

- Deps on fast-changing state tear down and rebuild the interval on every WS event.
- Under load the interval never actually fires → green tests, dead feature.
- Pattern: `const stateRef = useRef(state); stateRef.current = state;` then read `stateRef.current` inside the tick callback.

**Why:** Without ref mirroring, the staleness tripwire (or any periodic health check in `HydraFlowContext.jsx`) silently never trips under real event volume.
