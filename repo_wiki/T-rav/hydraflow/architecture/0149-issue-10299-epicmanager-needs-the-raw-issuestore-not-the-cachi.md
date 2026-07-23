---
id: 0149
topic: architecture
source_issue: 10299
source_phase: plan
created_at: 2026-07-22T17:49:09.980143+00:00
status: active
corroborations: 1
---

# EpicManager needs the raw IssueStore, not the CachingIssueStore decorator

Queue/worker occupancy state (`_active`, `_in_flight`, stage queues) lives on the raw `IssueStore` object, not on the `CachingIssueStore` decorator wrapped around it. When wiring execution-state derivation into `EpicManager` (src/epic.py), `service_registry.py` must pass the raw `store`, not `phase_store` or the caching wrapper — the wrapper doesn't expose live queue reads. Passing the wrong layer produces an `EpicManager` that always derives `idle` even when workers are actively holding issues.

**Why:** the caching decorator exists to shield read-heavy callers from IssueStore, but that indirection silently hides the mutable worker/queue state this feature depends on.
