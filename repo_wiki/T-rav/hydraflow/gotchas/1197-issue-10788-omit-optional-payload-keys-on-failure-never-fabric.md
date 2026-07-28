---
id: 1197
topic: gotchas
source_issue: 10788
source_phase: plan
created_at: 2026-07-28T09:50:57.002317+00:00
status: active
corroborations: 1
---

# Omit optional payload keys on failure — never fabricate zeros

When enriching `PRCreatedPayload` / `MergeUpdatePayload` with best-effort stats, a failed or dry-run read must omit keys entirely, not default to zero.

- `files_changed: 0` renders "0 files" in the timeline UI; an absent key is hidden.
- `get_pr_diff_stats` returns `{}` on failure; emit sites merge only returned keys.

**Why:** Zero is valid data the UI displays; absence signals "unknown" and preserves today's payload untouched.
