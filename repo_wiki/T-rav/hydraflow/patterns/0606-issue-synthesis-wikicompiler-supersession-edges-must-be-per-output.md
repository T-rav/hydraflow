---
id: 0606
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.351331+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# WikiCompiler supersession edges must be per-output, not cartesian

In `src/wiki_compiler.py`, `compile_topic_tracked` must resolve a mapping before any write: model-declared per-output `supersedes` list → normalized-title fallback → all-inputs-to-sole-output when `len(compiled) == 1` → abort-and-keep-active if unresolved.

Example: do not stamp every input's `superseded_by` with only the *first* output id.

**Why:** a shared/first-only id makes `superseded_by` traversal land an operator on unrelated guidance — confirmed live in `repo_wiki/T-rav/hydraflow/dependencies/`.
