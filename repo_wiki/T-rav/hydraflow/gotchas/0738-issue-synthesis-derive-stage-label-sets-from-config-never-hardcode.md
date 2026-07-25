---
id: 0738
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.863887+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0764
---

# Derive stage-label sets from config, never hardcode label lists

When code needs "all active pipeline stage labels" (e.g. to strip on close, or to scan for drift), add a single property like `active_stage_labels` in `src/config.py` and have every consumer (`PRManager.close_issue`, `LabelDriftWatcherLoop._reconcile`, `FakeGitHub.close_issue`) read from it — never re-list labels inline.

Example: terminal labels like `hydraflow-fixed` must be explicitly excluded from this set so caretaker/terminal semantics survive.

**Why:** A hardcoded list drifts from ADR-0002's label state machine the moment a new stage label is added, silently breaking close/drift logic.
