---
id: 0482
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.403103+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0494
---

# PRManager.close_issue label strips must be best-effort and 404-safe

Any label mutation added to `PRManager.close_issue` (e.g. stripping active stage labels on close) must use the `_remove_label` best-effort path and never block or fail the close itself — a missing label or a 404 from the label DELETE call is expected, not an error. Restrict the strip to dispatchable stage labels only; never touch `hydraflow-fixed` or human-required labels, or caretaker/terminal semantics break.

**Why:** close_issue is on the critical path for the merge flow — a hard failure on label cleanup would block issue closure entirely.
