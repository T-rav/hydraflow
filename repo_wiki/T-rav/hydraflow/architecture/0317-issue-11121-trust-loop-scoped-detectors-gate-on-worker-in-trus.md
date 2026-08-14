---
id: 0317
topic: architecture
source_issue: 11121
source_phase: plan
created_at: 2026-08-14T10:59:17.953034+00:00
status: active
corroborations: 1
---

# Trust-loop-scoped detectors gate on worker in TRUST_LOOP_WORKERS

Detectors that apply only to trust loops run inside the `worker in TRUST_LOOP_WORKERS` block in `TrustFleetSanityLoop._do_work`, mirroring `tick_error_ratio`.

Example: `detect_unproductive_streak` is placed in that block; a non-trust worker with a long warmup streak files nothing.

**Why:** Fleet-wide workers (e.g. `RepoWikiLoop`) emit statuses with different semantics; scoping prevents false-positive HITL escalations on loops the detector was not designed for.
