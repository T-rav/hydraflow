---
id: 1083
topic: testing
source_issue: 10575
source_phase: plan
created_at: 2026-07-26T00:41:55.611434+00:00
status: superseded
corroborations: 1
superseded_by: 1085
---

# Wiki code citations must be single-backtick `path:Symbol` spans

`wiki_drift_detector.py:32` only recognizes citations written as one backtick span combining path and symbol, e.g. `` `src/escape/metrics.py:latest_by_id` ``. Splitting path and symbol across separate spans or plain prose makes the citation invisible to drift checking, so a stale or fictional claim silently passes review. When writing or correcting entries under `repo_wiki/`, always cite as a single backtick-wrapped `path:Symbol`. **Why:** the entry's self-policing correctness depends entirely on this exact, parseable format.
