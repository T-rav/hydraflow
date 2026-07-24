---
id: 0497
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:03:19.171552+00:00
status: active
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
---

# Strip prose-colliding aliases in validate_draft, don't reject the term

`validate_draft` in `src/ubiquitous_language.py` should strip an alias that collides with live wiki prose rather than hard-rejecting the whole draft; reserve hard-reject for canonical-name collisions only.

Example: pass `wiki_root` (e.g. `terms_root.parent` from `src/term_proposer_loop.py`) into `validate_draft` as an optional parameter, defaulted to `None` so existing callers without `wiki_root` keep working unchanged.

**Why:** a colliding alias is a naming detail, not an identity conflict — rejecting the whole term throws away a valid definition over one bad alias.
