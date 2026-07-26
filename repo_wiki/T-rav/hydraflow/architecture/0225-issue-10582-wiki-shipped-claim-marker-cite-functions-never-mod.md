---
id: 0225
topic: architecture
source_issue: 10582
source_phase: plan
created_at: 2026-07-26T02:05:19.449625+00:00
status: active
corroborations: 1
---

# Wiki shipped-claim marker: cite functions, never module constants

In `repo_wiki/<slug>/gotchas/*.md`, a shipped-fix claim needs a ```json:entry``` block with `fixed_in_pr` + `code_refs`. `wiki_rot_citations.verify_cite_ast` only collects `FunctionDef`/`ClassDef` names — citing a module-level constant like `_SHA_MARKER` makes the claim read as uncorroborated drift and the rot detector files a false finding. Cite the enclosing function instead, e.g. `src/escape/detect.py:_added_paths_for_range` and its twin `src/audit/detect.py:_changed_paths_for_range`.

**Why:** AST-based corroboration silently ignores constants, so a constant-only ref looks identical to a stale/unverifiable claim to the detector.
