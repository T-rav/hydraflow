---
id: 2303
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.976187+00:00
status: superseded
corroborations: 1
supersedes: 2158
superseded_by: 2493
---

# Keep policy consumers as pure dict lookups; densify upstream

When a consumer needs id→row resolution, fix the index it reads, not the consumer's lookup logic. Add density upstream in `escape_by_id()` (`src/escape/metrics.py`) and `read_latest_index()` (`src/escape/ledger.py`) so every appended id resolves.

Example: `answered_surfacings` stays a plain dict consumer; only the map handed to it gets denser.

**Why:** Pushing resolution logic into each consumer duplicates tie-breaking and risks divergence from `_escape_supersedes`.
