---
id: 0739
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.866604+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# PRManager.close_issue label strips must be best-effort and 404-safe

Any label mutation added to `PRManager.close_issue` (e.g. stripping active stage labels on close) must use the `_remove_label` best-effort path and never block or fail the close itself — a missing label or a 404 from the label DELETE call is expected, not an error.

Example: restrict the strip to dispatchable stage labels only; never touch `hydraflow-fixed` or human-required labels, or caretaker/terminal semantics break.

**Why:** close_issue is on the critical path for the merge flow — a hard failure on label cleanup would block issue closure entirely.
