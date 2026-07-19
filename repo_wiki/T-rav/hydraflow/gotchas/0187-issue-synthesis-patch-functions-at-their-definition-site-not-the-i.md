---
id: 0187
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.152916+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Patch functions at their definition site, not the import site

Always patch functions at where they are defined, not where they are imported into the module under test.

Example: `@patch('hindsight.retain_safe')` not `@patch('my_module.retain_safe')` when `my_module` imports from `hindsight`.

**Why:** Patching the import site only replaces that module's local reference; all other callers continue using the real function, making the mock ineffective.
