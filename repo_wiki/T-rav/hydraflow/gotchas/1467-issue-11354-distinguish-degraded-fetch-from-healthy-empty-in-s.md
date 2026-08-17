---
id: 1467
topic: gotchas
source_issue: 11354
source_phase: plan
created_at: 2026-08-16T15:20:51.560208+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Distinguish degraded-fetch from healthy-empty in StreamView pipeline display

When `fetchHealth.pipeline` is degraded in `StreamView.jsx`, replace the default `No active work.` message with a warning-toned message naming status, consecutive failures, and relative `lastOkAt` (via `utils/timeFormat.js`, `theme.yellow`).

A healthy poll returning an empty board must still render `No active work.` — this is the counter-pin test case.

**Why:** Without the distinction, users cannot tell whether the board is empty because nothing is running or because the API is down.
