---
id: 0918
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:16:19.564535+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# ADR-0017's `_triage_single` naming went stale after the #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. ADR-0017 said both `increment_session_counter("triaged")` call sites lived in `_triage_single`, but the #6089/#6190 extraction moved them to `_triage_adr` (ADR fast-path) and `_triage_single_traced` (normal path, `src/triage_phase.py:550`).

Example: when splitting a function an ADR references by name, grep the ADR corpus for the old name before merging, or file a `hydraflow-find` issue immediately so drift doesn't wait for an unrelated PR rollup (like #10300) to surface it.

**Why:** no test caught this because ADR prose isn't type-checked; stale anchors mislead future readers into editing the wrong function and let "Enforced by" pointers rot unnoticed.
