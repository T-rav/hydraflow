---
id: 0516
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:10:56.111284+00:00
status: superseded
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
superseded_by: 0523
---

# Factor one shared word-boundary matcher for lint_paraphrases and validate_draft

Both `lint_paraphrases` and the new strip-guard in `validate_draft` (`src/ubiquitous_language.py`) need the same word-boundary alias-matching logic against wiki prose. Factor it into a single shared helper instead of duplicating the regex in two places.

**Why:** two independent regex implementations of "does this alias collide with prose" will drift apart over time, letting the proposer strip aliases the lint would still flag (or vice versa).
