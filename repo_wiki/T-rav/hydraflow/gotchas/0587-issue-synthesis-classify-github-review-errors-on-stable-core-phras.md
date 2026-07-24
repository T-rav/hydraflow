---
id: 0587
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.256656+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Classify GitHub review errors on stable core phrase, not full sentence

In `PRManager.submit_review`'s `except RuntimeError` handler, match error text on core phrases (`"approve your own pull request"`, `"request changes on your own pull request"`) rather than the full sentence including `cannot`/`can not`, so classification survives GitHub varying its exact phrasing.

Example: the generic-failure path (no phrase match) still returns `False` — don't broaden the match so far it swallows unrelated review failures.

**Why:** Full-sentence matching against an external service's error text is brittle to minor wording changes; core-phrase matching is robust without over-broadening into false positives.
