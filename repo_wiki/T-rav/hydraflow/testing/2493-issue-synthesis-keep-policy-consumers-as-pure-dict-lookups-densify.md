---
id: 2493
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.371689+00:00
status: active
corroborations: 1
supersedes: 2303
---

# Keep policy consumers as pure dict lookups; densify upstream

When a consumer needs id→row resolution, fix the index it reads, not the consumer's lookup logic. Add density upstream in `escape_by_id()` (`src/escape/metrics.py`) and `read_latest_index()` (`src/escape/ledger.py`) so every appended id resolves.

Example: `answered_surfacings` stays a plain dict consumer; only the map handed to it gets denser.

**Why:** Pushing resolution logic into each consumer duplicates tie-breaking and risks divergence from `_escape_supersedes`.
