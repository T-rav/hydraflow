---
id: 0515
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:10:56.110579+00:00
status: active
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
---

# Strip prose-colliding aliases in validate_draft, don't reject the term

In `src/ubiquitous_language.py`, `validate_draft` should strip an alias that collides with live wiki prose rather than hard-rejecting the whole draft — reserve hard-reject for canonical-name collisions only.

Example: pass `wiki_root` (e.g. `terms_root.parent` from `src/term_proposer_loop.py`) into `validate_draft`, defaulted to optional so existing callers without wiki_root still work unchanged.

**Why:** a colliding alias is a naming detail, not an identity conflict — rejecting the whole term throws away a valid definition over one bad alias.
