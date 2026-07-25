---
id: 0804
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:13:09.954761+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Classify GitHub review errors on stable core phrase, not full sentence

In `PRManager.submit_review`'s `except RuntimeError` handler, match error text on core phrases (`"approve your own pull request"`, `"request changes on your own pull request"`) rather than the full sentence including `cannot`/`can not`, so classification survives GitHub varying its exact phrasing.

Example: the generic-failure path (no phrase match) still returns `False` — don't broaden the match so far it swallows unrelated review failures.

**Why:** Full-sentence matching against an external service's error text is brittle to minor wording changes; core-phrase matching is robust without over-broadening into false positives.
