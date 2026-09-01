---
id: 1560
topic: gotchas
source_issue: 11969
source_phase: plan
created_at: 2026-09-01T11:15:55.080383+00:00
status: active
corroborations: 1
---

# Pin reset must discard memory_backlog:<slug> dedup key

When `MemoryBacklogLoop._revalidate_pins` resets a stale mirror from `issue-open` to `pending`, it MUST also discard the `memory_backlog:<slug>` dedup key in the same pass.

Example: reset writes `status: pending`, `issue: null`, and drops the dedup key — so the same tick's filing pass can pick it up.

**Why:** If the dedup key survives the reset, the mirror flips to `pending` and is then skipped forever (filing sees the key and short-circuits), permanently stranding the mirror.
