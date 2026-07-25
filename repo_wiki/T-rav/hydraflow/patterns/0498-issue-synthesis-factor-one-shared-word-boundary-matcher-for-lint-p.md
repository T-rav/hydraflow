---
id: 0498
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:39:48.843474+00:00
status: superseded
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
superseded_by: 0499
---

# Factor one shared word-boundary matcher for lint_paraphrases and validate_draft

Both `lint_paraphrases` and the new strip-guard in `validate_draft` (`src/ubiquitous_language.py`) need the same word-boundary alias-matching logic against wiki prose. Factor it into a single shared helper instead of duplicating the regex in two places.

**Why:** two independent regex implementations of "does this alias collide with prose" will drift apart over time, letting the proposer strip aliases the lint would still flag (or vice versa).
