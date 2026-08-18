---
id: 1481
topic: gotchas
source_issue: 11414
source_phase: plan
created_at: 2026-08-18T03:10:06.299897+00:00
status: active
corroborations: 1
---

# fetchPipeline error swallowing extends stale pipelineSnapshotAt windows

Rule: When assessing exposure duration for stale `pipelineSnapshotAt` state, account for `fetchPipeline`'s `.catch(() => {})` — a failed post-switch fetch leaves stale state standing until the next authoritative snapshot re-stamps.

Example: After `SELECT_REPO` clears the clock via `clearedPipeline()`, a failed `fetchPipeline` means the rail stays "resyncing" indefinitely — honest, but the resync chip becomes the only signal of a broken fetch.

**Why:** Error swallowing hides the gap between "reset cleared the clock" and "next snapshot arrived," making it impossible to distinguish transient resync from a permanently broken fetch.
