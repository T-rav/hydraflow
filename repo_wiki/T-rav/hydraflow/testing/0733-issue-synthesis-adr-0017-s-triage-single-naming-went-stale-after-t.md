---
id: 0733
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.324318+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# ADR-0017's `_triage_single` naming went stale after the #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. ADR-0017 said both `increment_session_counter("triaged")` call sites lived in `_triage_single`, but the #6089/#6190 extraction moved them to `_triage_adr` (ADR fast-path) and `_triage_single_traced` (normal path, `src/triage_phase.py:550`).

Example: when splitting a function an ADR references by name, grep the ADR corpus for the old name before merging, or file a `hydraflow-find` issue immediately so drift doesn't wait for an unrelated PR rollup (like #10300) to surface it.

**Why:** no test caught this because ADR prose isn't type-checked; stale anchors mislead future readers into editing the wrong function and let "Enforced by" pointers rot unnoticed.
