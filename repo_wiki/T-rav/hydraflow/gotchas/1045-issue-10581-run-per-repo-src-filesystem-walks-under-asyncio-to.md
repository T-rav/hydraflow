---
id: 1045
topic: gotchas
source_issue: 10581
source_phase: plan
created_at: 2026-07-26T01:56:36.497443+00:00
status: active
corroborations: 1
---

# Run per-repo src/ filesystem walks under asyncio.to_thread in RepoWikiLoop

A synchronous full-`src/` walk (building a symbol definition index) belongs in `asyncio.to_thread`, called once per repo per tick, wrapped in a per-repo try/except so one repo's failure doesn't kill the loop's stats return.

In `RepoWikiLoop`'s phase-9c wiring for `detect_prose_drift`, a raising call is swallowed per-repo and the tick still returns `stats`.

**Why:** keeps the async tick loop non-blocking while tolerating a heuristic detector that can legitimately throw on malformed source.
