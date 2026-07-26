---
id: 0540
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.245194+00:00
status: active
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
---

# Factor one shared word-boundary matcher for lint_paraphrases and validate_draft

Both `lint_paraphrases` and the new strip-guard in `validate_draft` (`src/ubiquitous_language.py`) need the same word-boundary alias-matching logic against wiki prose. Factor it into a single shared helper instead of duplicating the regex in two places.

**Why:** two independent regex implementations of "does this alias collide with prose" will drift apart over time, letting the proposer strip aliases the lint would still flag (or vice versa).
