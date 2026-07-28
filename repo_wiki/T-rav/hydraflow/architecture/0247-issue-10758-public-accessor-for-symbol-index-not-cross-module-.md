---
id: 0247
topic: architecture
source_issue: 10758
source_phase: plan
created_at: 2026-07-27T23:48:31.703678+00:00
status: active
corroborations: 1
---

# Public accessor for symbol index, not cross-module _ import

Expose a public cached function when other modules need an internal helper's result. In `src/wiki_rot_citations.py`, add `module_symbols(repo_root, module_path) -> frozenset[str]` rather than importing `_collect_defined_symbols` across modules.

- Cross-module `_`-prefixed imports are a repo gotcha flagged by the gotchas audit.
- Routing `verify_cite_ast` through the same accessor ensures one symbol index per run, built once.

**Why:** Duplicating the parse or importing a private symbol either wastes CPU or couples modules to implementation internals the gotchas audit will reject.
