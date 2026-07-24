---
id: 0693
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.862933+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# ADR-0017's `_triage_single` naming went stale after the #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. ADR-0017 said both `increment_session_counter("triaged")` call sites lived in `_triage_single`, but the #6089/#6190 extraction moved them to `_triage_adr` (ADR fast-path) and `_triage_single_traced` (normal path, `src/triage_phase.py:550`).

Example: when splitting a function an ADR references by name, grep the ADR corpus for the old name before merging, or file a `hydraflow-find` issue immediately so drift doesn't wait for an unrelated PR rollup (like #10300) to surface it.

**Why:** no test caught this because ADR prose isn't type-checked; stale anchors mislead future readers into editing the wrong function and let "Enforced by" pointers rot unnoticed.
