---
id: 1889
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:06.241422+00:00
status: superseded
corroborations: 1
supersedes: 1784
superseded_by: 2016
---

# Wiki code citations must be single-backtick path:Symbol spans

wiki_drift_detector.py:32 only recognizes citations written as one backtick span combining path and symbol (e.g. `src/escape/metrics.py:latest_by_id`).

Example: splitting path and symbol across separate spans or plain prose makes the citation invisible to drift checking, so a stale or fictional claim silently passes review.

**Why:** The entry's self-policing correctness depends entirely on this exact, parseable format.
