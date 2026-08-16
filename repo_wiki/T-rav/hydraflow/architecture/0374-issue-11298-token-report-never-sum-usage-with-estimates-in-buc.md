---
id: 0374
topic: architecture
source_issue: 11298
source_phase: plan
created_at: 2026-08-16T05:49:45.238785+00:00
status: active
corroborations: 1
---

# Token report: never sum usage with estimates in _bucket_stats

Report token components separately from estimates; never fallback-sum them into one figure. `_bucket_stats` in `src/token_report.py` emits `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, and `est_tokens` as distinct fields, plus a `unit` tag (`"usage"`/`"estimate"`/`"mixed"`). The `_tokens()` helper that did `total_tokens or total_est_tokens` is deleted.

**Why:** Summing real usage with character-based estimates let failed zero-usage spawns with multi-MB transcripts dominate ranking — the "plan loop = 86% of tokens" finding that sized four merged PRs was an artifact of this fallback.
