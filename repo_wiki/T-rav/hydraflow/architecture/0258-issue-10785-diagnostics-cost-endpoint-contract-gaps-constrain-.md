---
id: 0258
topic: architecture
source_issue: 10785
source_phase: plan
created_at: 2026-07-28T09:16:36.126407+00:00
status: active
corroborations: 1
---

# Diagnostics cost endpoint contract gaps constrain UI design

Three `/api/diagnostics/cost/` endpoints have shape limitations the UI must accommodate:
- `cost-by-phase` returns `dict[phase→tokens]` only (no cost field) via `factory_metrics.cost_by_phase`.
- `cost_inferences.jsonl` carries no run/session id.
- `_RANGE_MAP` allows only `24h|7d|30d|90d`.

Per-stage cost badges must read from `cost/rolling-24h.by_phase` (which carries `cost_usd`), not `cost-by-phase`. Current-run cost ships as rolling-24h total, labelled `last 24h`.

**Why:** Treating token-only endpoints as cost sources, or expecting run-scoped totals, produces wrong numbers silently.
