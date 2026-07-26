---
id: 0573
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.789254+00:00
status: active
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
---

# WikiCompiler supersession edges must be per-output, not cartesian

In `src/wiki_compiler.py:712-729`, `compile_topic_tracked` computed `superseded_ids` once and reused it for every synthesis output, then stamped every input's `superseded_by` with only the *first* output id. Fix by resolving a mapping before any write: model-declared per-output `supersedes` list → normalized-title fallback → all-inputs-to-sole-output when `len(compiled) == 1` → abort-and-keep-active if unresolved. Any future generator that writes N inputs to M outputs needs this same per-edge resolution, not a single shared id.

**Why:** a shared/first-only id makes `superseded_by` traversal land an operator on unrelated guidance — confirmed live in `repo_wiki/T-rav/hydraflow/dependencies/`.
