---
id: 0634
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.583514+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Classify GitHub review errors on stable core phrase, not full sentence

In `PRManager.submit_review`'s `except RuntimeError` handler, match error text on core phrases (`"approve your own pull request"`, `"request changes on your own pull request"`) rather than the full sentence including `cannot`/`can not`, so classification survives GitHub varying its exact phrasing.

Example: the generic-failure path (no phrase match) still returns `False` — don't broaden the match so far it swallows unrelated review failures.

**Why:** Full-sentence matching against an external service's error text is brittle to minor wording changes; core-phrase matching is robust without over-broadening into false positives.
