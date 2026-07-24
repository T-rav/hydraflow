---
id: 0440
topic: gotchas
source_issue: 10394
source_phase: plan
created_at: 2026-07-24T05:04:19.027205+00:00
status: active
corroborations: 1
---

# PRManager.close_issue label strips must be best-effort and 404-safe

Any label mutation added to `PRManager.close_issue` (e.g. stripping active stage labels on close) must use the `_remove_label` best-effort path and never block or fail the close itself — a missing label or a 404 from the label DELETE call is expected, not an error. Restrict the strip to dispatchable stage labels only; never touch `hydraflow-fixed` or human-required labels, or caretaker/terminal semantics break.

**Why:** close_issue is on the critical path for the merge flow — a hard failure on label cleanup would block issue closure entirely.
