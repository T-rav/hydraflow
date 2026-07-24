---
id: 0775
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.329242+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# ADR-0017's `_triage_single` naming went stale after the #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. ADR-0017 said both `increment_session_counter("triaged")` call sites lived in `_triage_single`, but the #6089/#6190 extraction moved them to `_triage_adr` (ADR fast-path) and `_triage_single_traced` (normal path, `src/triage_phase.py:550`).

Example: when splitting a function an ADR references by name, grep the ADR corpus for the old name before merging, or file a `hydraflow-find` issue immediately so drift doesn't wait for an unrelated PR rollup (like #10300) to surface it.

**Why:** no test caught this because ADR prose isn't type-checked; stale anchors mislead future readers into editing the wrong function and let "Enforced by" pointers rot unnoticed.
