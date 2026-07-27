---
id: 0566
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.754827+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0600
---

# Strip prose-colliding aliases in validate_draft, don't reject the term

In `src/ubiquitous_language.py`, `validate_draft` should strip an alias that collides with live wiki prose rather than hard-rejecting the whole draft — reserve hard-reject for canonical-name collisions only.

Example: pass `wiki_root` (e.g. `terms_root.parent` from `src/term_proposer_loop.py`) into `validate_draft`, defaulted to optional so existing callers without wiki_root still work unchanged. See also: patterns — Factor one shared word-boundary matcher for lint_paraphrases and validate_draft.

**Why:** a colliding alias is a naming detail, not an identity conflict — rejecting the whole term throws away a valid definition over one bad alias.
