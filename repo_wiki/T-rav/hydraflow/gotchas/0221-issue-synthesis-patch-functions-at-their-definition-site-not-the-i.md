---
id: 0221
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.794886+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Patch functions at their definition site, not the import site

Always patch functions at where they are defined, not where they are imported into the module under test.

Example: `@patch('hindsight.retain_safe')` not `@patch('my_module.retain_safe')` when `my_module` imports from `hindsight`.

**Why:** Patching the import site only replaces that module's local reference; all other callers continue using the real function, making the mock ineffective.
