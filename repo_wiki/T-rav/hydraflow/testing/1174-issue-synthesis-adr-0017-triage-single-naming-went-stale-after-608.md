---
id: 1174
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.859499+00:00
status: active
corroborations: 1
supersedes: 1105
---

# ADR-0017 _triage_single naming went stale after #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. When splitting a function an ADR references by name, grep the ADR corpus for the old name before merging.

Example: ADR-0017 said increment_session_counter("triaged") lived in _triage_single, but #6089/#6190 moved them to _triage_adr and _triage_single_traced (src/triage_phase.py:550).

**Why:** No test caught this because ADR prose isn't type-checked; stale anchors mislead future readers into editing the wrong function.
