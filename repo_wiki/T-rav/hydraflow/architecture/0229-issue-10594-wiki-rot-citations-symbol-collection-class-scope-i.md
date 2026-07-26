---
id: 0229
topic: architecture
source_issue: 10594
source_phase: plan
created_at: 2026-07-26T04:15:06.679605+00:00
status: active
corroborations: 1
---

# wiki_rot_citations symbol collection: class scope in, function scope out

When widening `_collect_defined_symbols` in `src/wiki_rot_citations.py` to bind assignment targets, recurse into `ClassDef` bodies but never into function bodies. A bare `ast.walk` over `Assign`/`AnnAssign` admits function locals too, making `verify_cite_ast` nearly unfalsifiable and flooding `fuzzy_suggest` candidates with throwaway names. Class scope isn't optional either — e.g. `_SELF_CHECK_CHECKLIST` in `src/agent.py` is a class attribute, not module-level, so a top-level-only walk misses it.

**Why:** over-widening silently suppresses both cite rot and shipped-claim rot (via `_shipped_claim_corroborated`), defeating the detector's purpose.
