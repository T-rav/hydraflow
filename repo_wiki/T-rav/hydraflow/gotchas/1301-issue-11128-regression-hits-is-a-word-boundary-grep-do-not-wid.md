---
id: 1301
topic: gotchas
source_issue: 11128
source_phase: plan
created_at: 2026-08-14T12:04:30.040476+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# regression_hits is a word-boundary grep — do not widen it

`regression_hits` matches issue numbers via word-boundary grep over `tests/`. A file merely mentioning the number can satisfy it, risking false auto-close of genuinely unencoded escapes.

Keep this fuzziness as-is; it already governs the pre-filing path. Guard against false positives with a counter-pin test (same state, no pin in tree ⇒ issues stay open).

**Why:** Widening the match or trusting it without a counter-pin closes real HITL issues on coincidental mentions.
