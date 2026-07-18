---
id: 0119
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.599284+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Patch functions at their definition site, not the import site

Always patch functions at where they are defined, not where they are imported into the module under test.

Example: `@patch('hindsight.retain_safe')` not `@patch('my_module.retain_safe')` when `my_module` imports from `hindsight`.

**Why:** Patching the import site only replaces that module's local reference; all other callers continue using the real function, making the mock ineffective.
