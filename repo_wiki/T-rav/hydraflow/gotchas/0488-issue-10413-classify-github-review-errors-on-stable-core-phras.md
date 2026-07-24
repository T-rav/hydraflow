---
id: 0488
topic: gotchas
source_issue: 10413
source_phase: plan
created_at: 2026-07-24T06:07:17.313495+00:00
status: active
corroborations: 1
---

# Classify GitHub review errors on stable core phrase, not full sentence

In `PRManager.submit_review`'s `except RuntimeError` handler, match error text on core phrases (`"approve your own pull request"`, `"request changes on your own pull request"`) rather than the full sentence including `cannot`/`can not`, so classification survives GitHub varying its exact phrasing. The generic-failure path (no phrase match) still returns `False` — don't broaden the match so far it swallows unrelated review failures.

**Why:** full-sentence matching against an external service's error text is brittle to minor wording changes; core-phrase matching is robust without over-broadening into false positives.
