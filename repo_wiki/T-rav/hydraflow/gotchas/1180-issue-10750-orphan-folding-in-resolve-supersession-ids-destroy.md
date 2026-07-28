---
id: 1180
topic: gotchas
source_issue: 10750
source_phase: plan
created_at: 2026-07-27T22:53:53.519922+00:00
status: active
corroborations: 1
---

# Orphan folding in _resolve_supersession_ids destroys unclaimed entries

In `WikiCompiler._resolve_supersession_ids` (`src/wiki_compiler.py:1229`), unclaimed active ids are folded onto `per_entry[0]` (lines 1261–1265); `_flow_validate` (line 866) then flips every active input to `superseded`. An entry no LLM output names gets silently destroyed. Fix: unclaimed entries stay `active`; a zero-claim synthesis aborts fail-closed. **Why:** Folding orphans onto unrelated successors deletes true lessons — the #10566 defect recurring for orphans only, which the gauntlet misses because it tests claimed inputs.
