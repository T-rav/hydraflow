---
id: 0479
topic: patterns
source_issue: 10464
source_phase: plan
created_at: 2026-07-24T15:39:21.687929+00:00
status: superseded
corroborations: 1
superseded_by: 0481
---

# Strip prose-colliding aliases in validate_draft, don't reject the term

In `src/ubiquitous_language.py`, `validate_draft` should strip an alias that collides with live wiki prose rather than hard-rejecting the whole draft — reserve hard-reject for canonical-name collisions only. Pass `wiki_root` (e.g. `terms_root.parent` from `src/term_proposer_loop.py`) into `validate_draft`, defaulted to optional so existing callers without wiki_root still work unchanged. **Why:** a colliding alias is a naming detail, not an identity conflict — rejecting the whole term throws away a valid definition over one bad alias.
