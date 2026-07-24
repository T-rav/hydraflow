---
id: 0745
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.881997+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Classify GitHub review errors on stable core phrase, not full sentence

In `PRManager.submit_review`'s `except RuntimeError` handler, match error text on core phrases (`"approve your own pull request"`, `"request changes on your own pull request"`) rather than the full sentence including `cannot`/`can not`, so classification survives GitHub varying its exact phrasing.

Example: the generic-failure path (no phrase match) still returns `False` — don't broaden the match so far it swallows unrelated review failures.

**Why:** Full-sentence matching against an external service's error text is brittle to minor wording changes; core-phrase matching is robust without over-broadening into false positives.
