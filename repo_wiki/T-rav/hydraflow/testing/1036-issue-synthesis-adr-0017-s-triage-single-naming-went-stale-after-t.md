---
id: 1036
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.478476+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# ADR-0017's `_triage_single` naming went stale after the #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. ADR-0017 said both increment_session_counter("triaged") call sites lived in _triage_single, but the #6089/#6190 extraction moved them to _triage_adr (ADR fast-path) and _triage_single_traced (normal path, src/triage_phase.py:550).

Example: when splitting a function an ADR references by name, grep the ADR corpus for the old name before merging, or file a hydraflow-find issue immediately so drift doesn't wait for an unrelated PR rollup (like #10300) to surface it.

**Why:** no test caught this because ADR prose isn't type-checked; stale anchors mislead future readers into editing the wrong function and let "Enforced by" pointers rot unnoticed.
