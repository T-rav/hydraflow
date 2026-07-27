---
id: 0694
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:37:52.927038+00:00
status: active
corroborations: 1
supersedes: 0649
---

# WikiCompiler supersession edges must be per-output, not cartesian

In `src/wiki_compiler.py:712-729`, resolve supersession edges per-output before any write: model-declared per-output `supersedes` list → normalized-title fallback → all-inputs-to-sole-output when `len(compiled) == 1` → abort-and-keep-active if unresolved.

Example: Any future generator writing N inputs to M outputs needs per-edge resolution, not a single shared id — stamping every input's `superseded_by` with only the first output id makes traversal land on unrelated guidance.

**Why:** A shared/first-only id makes `superseded_by` traversal land an operator on unrelated guidance — confirmed live in `repo_wiki/T-rav/hydraflow/dependencies/`.
