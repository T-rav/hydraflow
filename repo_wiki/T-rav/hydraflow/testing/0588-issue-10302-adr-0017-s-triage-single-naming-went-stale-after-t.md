---
id: 0588
topic: testing
source_issue: 10302
source_phase: plan
created_at: 2026-07-24T03:55:54.536735+00:00
status: active
corroborations: 1
---

# ADR-0017's `_triage_single` naming went stale after the #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. ADR-0017 said both `increment_session_counter("triaged")` call sites lived in `_triage_single`, but the #6089/#6190 extraction moved them to `_triage_adr` (ADR fast-path) and `_triage_single_traced` (normal path, `src/triage_phase.py:550`). No test caught this because ADR prose isn't type-checked. When splitting a function an ADR references by name, grep the ADR corpus for the old name before merging, or file a `hydraflow-find` issue immediately so drift doesn't wait for an unrelated PR rollup (like #10300) to surface it.

**Why:** stale ADR anchors mislead future readers into editing the wrong function and let "Enforced by" pointers rot unnoticed.
