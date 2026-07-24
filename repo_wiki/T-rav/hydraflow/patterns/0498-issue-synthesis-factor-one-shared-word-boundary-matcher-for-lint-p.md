---
id: 0498
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:03:19.174968+00:00
status: active
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
---

# Factor one shared word-boundary matcher for lint_paraphrases and validate_draft

Factor the word-boundary alias-matching regex into a single shared helper instead of duplicating it.

Example: both `lint_paraphrases` and the strip-guard in `validate_draft` (`src/ubiquitous_language.py`) need identical logic to match an alias against wiki prose — extract one helper both call. See also: patterns — Strip prose-colliding aliases in validate_draft, don't reject the term.

**Why:** two independent regex implementations of "does this alias collide with prose" will drift apart over time, letting the proposer strip aliases the lint would still flag (or vice versa).
