---
id: 0480
topic: patterns
source_issue: 10464
source_phase: plan
created_at: 2026-07-24T15:39:21.687941+00:00
status: superseded
corroborations: 1
superseded_by: 0481
---

# Factor one shared word-boundary matcher for lint_paraphrases and validate_draft

Both `lint_paraphrases` and the new strip-guard in `validate_draft` (src/ubiquitous_language.py) need the same word-boundary alias-matching logic against wiki prose. Factor it into a single shared helper instead of duplicating the regex in two places. **Why:** two independent regex implementations of "does this alias collide with prose" will drift apart over time, letting the proposer strip aliases the lint would still flag (or vice versa).
