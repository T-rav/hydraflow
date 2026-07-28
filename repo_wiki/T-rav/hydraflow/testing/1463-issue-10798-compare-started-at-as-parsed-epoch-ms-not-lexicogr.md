---
id: 1463
topic: testing
source_issue: 10798
source_phase: plan
created_at: 2026-07-28T10:05:46.407760+00:00
status: active
corroborations: 1
---

# Compare `started_at` as parsed epoch-ms, not lexicographic string `>`

ISO timestamps with non-`Z` offsets (e.g. `+02:00`) sort wrong under raw string `>`. Parse to epoch-ms before comparing in `pickLatestSession`.

- Missing/unparseable `started_at` ranks lowest.
- Ties keep earlier array index (preserves strict `>` semantics).
- Behaviour is identical for Z-normalised ISO strings the reducer produces today; the offset case is a strict improvement.

**Why:** A `+02:00` session chronologically newer than a `Z` session can have a lexicographically smaller string, silently selecting the wrong session as "latest."
