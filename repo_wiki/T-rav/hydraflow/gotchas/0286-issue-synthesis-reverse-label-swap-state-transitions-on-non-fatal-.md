---
id: 0286
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T04:10:53.481571+00:00
status: active
corroborations: 1
supersedes: 0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281
---

# Reverse label-swap state transitions on non-fatal exceptions

Rule: Wrap label-swap + operation + cleanup in try/except and reverse the transition on non-fatal errors, per the ADR-0002 labels-as-state-machine model.

Example: if a label is swapped `plan → implement` but the follow-up API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate label states with no automated recovery path.
