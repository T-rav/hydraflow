---
id: 1567
topic: gotchas
source_issue: 12058
source_phase: plan
created_at: 2026-09-02T22:01:19.186889+00:00
status: active
corroborations: 1
---

# Dedup key consumption timing in over-cap filing

Defer dedup key writes until after the summary issue creation returns a non-zero number; spending keys before stamping frontmatter creates orphaned entries invisible to re-filing guards.

Example: `src/memory_backlog_loop.py` over-cap path collects entries, calls `file_overflow_summary()`, stamps frontmatter + dedup keys, then commits atomically.

**Why:** Early key consumption orphans entries; guards see no spent key and re-file them forever.
