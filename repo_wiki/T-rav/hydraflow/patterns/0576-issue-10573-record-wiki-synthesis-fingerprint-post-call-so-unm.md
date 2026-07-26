---
id: 0576
topic: patterns
source_issue: 10573
source_phase: plan
created_at: 2026-07-26T00:55:00.255824+00:00
status: active
corroborations: 1
---

# Record wiki synthesis fingerprint post-call so unmerged PRs self-heal

In the Phase 8 skip guard (`src/repo_wiki_loop.py`, #10573), the fingerprint is recorded **after** a non-raising `compile_topic_tracked` call, using the post-call active set — never pre-call. If synthesis raises, nothing is recorded (next tick retries). If synthesis succeeds but its maintenance PR never merges, the on-disk tracked-active set still matches what was recorded, so the next tick correctly compares against real state and keeps skipping — no drift from an abandoned PR. `_drain_maintenance_queue`'s `force-compile` path must explicitly invalidate the stored fingerprint or force-compile becomes a no-op once a record exists.

**Why:** recording pre-call would let an unmerged maintenance PR desync the fingerprint from real repo content, wrongly skipping synthesis the topic still needs.
