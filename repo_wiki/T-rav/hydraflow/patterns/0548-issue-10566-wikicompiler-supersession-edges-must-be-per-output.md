---
id: 0548
topic: patterns
source_issue: 10566
source_phase: plan
created_at: 2026-07-25T23:57:01.883125+00:00
status: superseded
corroborations: 1
superseded_by: 0550
---

# WikiCompiler supersession edges must be per-output, not cartesian

In `src/wiki_compiler.py:712-729`, `compile_topic_tracked` computed `superseded_ids` once and reused it for every synthesis output, then stamped every input's `superseded_by` with only the *first* output id — so every output claims all inputs, but inputs point at one arbitrary output. Fix by resolving a mapping before any write: model-declared per-output `supersedes` list → normalized-title fallback → all-inputs-to-sole-output when `len(compiled) == 1` → abort-and-keep-active if unresolved. Any future generator that writes N inputs to M outputs needs this same per-edge resolution, not a single shared id.

**Why:** a shared/first-only id makes `superseded_by` traversal land an operator on unrelated guidance — confirmed live in `repo_wiki/T-rav/hydraflow/dependencies/`.
