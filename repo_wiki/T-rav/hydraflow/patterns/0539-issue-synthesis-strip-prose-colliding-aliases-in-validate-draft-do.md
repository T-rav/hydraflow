---
id: 0539
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.244395+00:00
status: active
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
---

# Strip prose-colliding aliases in validate_draft, don't reject the term

In `src/ubiquitous_language.py`, `validate_draft` should strip an alias that collides with live wiki prose rather than hard-rejecting the whole draft — reserve hard-reject for canonical-name collisions only.

Example: pass `wiki_root` (e.g. `terms_root.parent` from `src/term_proposer_loop.py`) into `validate_draft`, defaulted to optional so existing callers without wiki_root still work unchanged. See also: patterns — Factor one shared word-boundary matcher for lint_paraphrases and validate_draft.

**Why:** a colliding alias is a naming detail, not an identity conflict — rejecting the whole term throws away a valid definition over one bad alias.
