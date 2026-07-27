---
id: 1362
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.360047+00:00
status: active
corroborations: 1
supersedes: 1288
---

# Wiki code citations must be single-backtick path:Symbol spans

wiki_drift_detector.py:32 only recognizes citations written as one backtick span combining path and symbol (e.g. `src/escape/metrics.py:latest_by_id`).

Example: splitting path and symbol across separate spans or plain prose makes the citation invisible to drift checking, so a stale or fictional claim silently passes review.

**Why:** The entry's self-policing correctness depends entirely on this exact, parseable format.
