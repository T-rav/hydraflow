---
id: 0370
topic: architecture
source_issue: 11306
source_phase: plan
created_at: 2026-08-16T05:13:33.717461+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Wrap localStorage access in try/catch per _readStoredConsoleMode pattern

All localStorage reads/writes in the classic console must be wrapped in try/catch, mirroring `_readStoredConsoleMode` in `App.jsx`. Applied to dismissed-notice hydration (`DISMISSED_NOTICES_KEY`) in `HydraFlowContext.jsx` initial state. **Why:** Unwrapped localStorage access throws in restricted iframe or SSR contexts, crashing the console on load.
