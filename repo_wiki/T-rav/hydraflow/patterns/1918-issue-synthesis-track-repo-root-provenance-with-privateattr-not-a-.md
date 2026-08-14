---
id: 1918
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:26.985062+00:00
status: active
corroborations: 1
supersedes: 1820
---

# Track repo_root provenance with PrivateAttr, not a public field

Record whether `repo_root` was auto-detected (sentinel expanded) vs caller-supplied using a `PrivateAttr` on `HydraFlowConfig`, set on **both** branches of `_resolve_base_paths`.

Example: `PrivateAttr` keeps serialization, schema, and equality unaffected; `model_dump()` gains no new key. `model_copy` and re-validation paths can resurrect a stale flag if you set it in only one branch.

**Why:** A public field would pollute the config schema and break equality checks; a single-branch assignment silently loses the flag on copy/re-validate.
