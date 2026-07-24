---
id: 0677
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.472097+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Derive stage-label sets from config, never hardcode label lists

When code needs "all active pipeline stage labels" (e.g. to strip on close, or to scan for drift), add a single property like `active_stage_labels` in `src/config.py` and have every consumer (`PRManager.close_issue`, `LabelDriftWatcherLoop._reconcile`, `FakeGitHub.close_issue`) read from it — never re-list labels inline.

Example: terminal labels like `hydraflow-fixed` must be explicitly excluded from this set so caretaker/terminal semantics survive.

**Why:** A hardcoded list drifts from ADR-0002's label state machine the moment a new stage label is added, silently breaking close/drift logic.
