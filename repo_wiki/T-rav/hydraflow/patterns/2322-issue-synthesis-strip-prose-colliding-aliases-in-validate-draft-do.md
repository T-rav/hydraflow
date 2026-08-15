---
id: 2322
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T05:19:55.602299+00:00
status: active
corroborations: 1
supersedes: 2202
---

# Strip prose-colliding aliases in validate_draft, don't reject term

In `src/ubiquitous_language.py`, `validate_draft` should strip an alias that collides with live wiki prose rather than hard-rejecting the whole draft — reserve hard-reject for canonical-name collisions only.

Example: Pass `wiki_root` (e.g. `terms_root.parent` from `src/term_proposer_loop.py`) into `validate_draft`, defaulted to optional so existing callers without `wiki_root` still work unchanged. See also: [patterns] — Factor one shared word-boundary matcher.

**Why:** A colliding alias is a naming detail, not an identity conflict — rejecting the whole term throws away a valid definition over one bad alias.
