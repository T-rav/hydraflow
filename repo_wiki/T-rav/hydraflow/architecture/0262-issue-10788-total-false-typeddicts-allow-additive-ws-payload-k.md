---
id: 0262
topic: architecture
source_issue: 10788
source_phase: plan
created_at: 2026-07-28T09:50:57.002367+00:00
status: active
corroborations: 1
---

# total=False TypedDicts allow additive WS payload keys without migration

Extend `PRCreatedPayload` / `MergeUpdatePayload` by adding optional keys — no schema migration or event-registry change needed.

- Both payloads are `total=False` TypedDicts in `src/models.py`.
- `HydraFlowEvent.data` has no key allowlist, so new keys reach the WebSocket verbatim.
- Example: adding `commit_sha`, `files_changed`, `additions`, `deletions` required zero changes to the event bus.

**Why:** The bus is pass-through by design; understanding this prevents unnecessary coupling changes when enriching payloads.
