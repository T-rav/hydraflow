---
id: 0283
topic: architecture
source_issue: 10874
source_phase: plan
created_at: 2026-07-31T06:49:10.357915+00:00
status: active
corroborations: 1
---

# AST import guards must skip string data like graph node labels

When scanning `src/`, `tests/`, `scripts/` for `src.`-prefixed imports, match only `ast.Import` / `ast.ImportFrom` nodes and `patch` / `setattr` first-arg string literals. Never match arbitrary string data.

Erosion/extractor tests use `"src.foo"` as graph node labels — a naive grep or AST walk over all strings produces false positives and trips the guard.

Follow the `test_src_does_not_import_scripts.py` shape: `rglob` the trees at runtime, never hardcode file lists.

**Why:** String data that coincidentally contains `src.` is not an import and must not fail the architecture guard.
