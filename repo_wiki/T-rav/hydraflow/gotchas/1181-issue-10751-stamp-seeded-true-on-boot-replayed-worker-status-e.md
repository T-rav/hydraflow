---
id: 1181
topic: gotchas
source_issue: 10751
source_phase: plan
created_at: 2026-07-27T23:15:11.981931+00:00
status: active
corroborations: 1
---

# Stamp seeded=True on boot-replayed worker status events

Set `seeded=True` on every `BackgroundWorkerStatusPayload` emitted by `_seed_background_worker_statuses` in `src/orchestrator.py`. Mirror the `enabled` field precedent from #10739: add `seeded: NotRequired[bool]` to `BackgroundWorkerStatusPayload` in `src/models.py`, set only in the seed path. Live cycle publishes never set it.

**Why:** Without provenance, every orchestrator restart republishes persisted `error` statuses as fresh `BACKGROUND_WORKER_STATUS` events, fabricating failures that never happened this session.
