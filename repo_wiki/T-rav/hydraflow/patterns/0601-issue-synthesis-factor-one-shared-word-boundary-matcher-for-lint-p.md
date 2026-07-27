---
id: 0601
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:31:18.165031+00:00
status: active
corroborations: 1
supersedes: 0567
---

# Factor one shared word-boundary matcher for lint_paraphrases and validate_draft

Both `lint_paraphrases` and the strip-guard in `validate_draft` (`src/ubiquitous_language.py`) need the same word-boundary alias-matching logic against wiki prose. Factor it into a single shared helper instead of duplicating the regex.

Example: One shared function in `src/ubiquitous_language.py` called by both `lint_paraphrases` and `validate_draft`.

**Why:** Two independent regex implementations of "does this alias collide with prose" will drift apart over time, letting the proposer strip aliases the lint would still flag (or vice versa).
