---
id: 1575
topic: gotchas
source_issue: 12059
source_phase: plan
created_at: 2026-09-02T22:09:40.835488+00:00
status: active
corroborations: 1
---

# Couple regression annotations to epic body entries to prevent mass silencing

Every annotated regression file must correspond to a RED-verdict entry in the epic body. This diff-review guard prevents mass-annotation without classification. Example: if P5 annotates `regression_issue_6703.py` with `blocked-on #12059` but the epic body lacks a failure line for #6703, review fails. Rejection criterion: "annotation without epic entry." Why: The cheapest path to passing P5/P6 is annotating all 44 issues without classifying, burying real bugs behind permanent exemption.
