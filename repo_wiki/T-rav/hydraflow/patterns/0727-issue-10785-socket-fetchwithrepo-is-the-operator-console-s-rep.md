---
id: 0727
topic: patterns
source_issue: 10785
source_phase: plan
created_at: 2026-07-28T09:16:36.126375+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# socket.fetchWithRepo is the operator console's repo-scoped fetch seam

Use `socket.fetchWithRepo` (received as the `socket` context prop in `OperatorConsole.jsx`) for any read-only endpoint call from the console — it automatically applies `repo=<slug>|__all__` scoping.

- `__all__` yields cross-repo totals; a single slug yields repo-scoped data.
- Depend on `selectedRepoSlug` + a timer (e.g. `COST_POLL_MS`) — never refetch on every WebSocket frame.

**Why:** The console only receives the WebSocket slice; `fetchWithRepo` is the existing HTTP seam, and endpoints like `/api/diagnostics/cost/*` scan JSONL files, so per-frame refetching would hammer them.
