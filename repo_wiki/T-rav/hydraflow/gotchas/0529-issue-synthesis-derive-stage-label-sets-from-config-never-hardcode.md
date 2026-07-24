---
id: 0529
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.796886+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Derive stage-label sets from config, never hardcode label lists

When code needs "all active pipeline stage labels" (e.g. to strip on close, or to scan for drift), add a single property like `active_stage_labels` in `src/config.py` and have every consumer (`PRManager.close_issue`, `LabelDriftWatcherLoop._reconcile`, `FakeGitHub.close_issue`) read from it — never re-list labels inline.

Example: terminal labels like `hydraflow-fixed` must be explicitly excluded from this set so caretaker/terminal semantics survive.

**Why:** A hardcoded list drifts from ADR-0002's label state machine the moment a new stage label is added, silently breaking close/drift logic.
