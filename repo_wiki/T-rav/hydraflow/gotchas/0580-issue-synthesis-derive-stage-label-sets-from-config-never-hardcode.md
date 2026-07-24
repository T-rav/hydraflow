---
id: 0580
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.220666+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Derive stage-label sets from config, never hardcode label lists

When code needs "all active pipeline stage labels" (e.g. to strip on close, or to scan for drift), add a single property like `active_stage_labels` in `src/config.py` and have every consumer (`PRManager.close_issue`, `LabelDriftWatcherLoop._reconcile`, `FakeGitHub.close_issue`) read from it — never re-list labels inline.

Example: terminal labels like `hydraflow-fixed` must be explicitly excluded from this set so caretaker/terminal semantics survive.

**Why:** A hardcoded list drifts from ADR-0002's label state machine the moment a new stage label is added, silently breaking close/drift logic.
