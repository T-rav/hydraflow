---
id: 0085
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.516392+00:00
status: superseded
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
superseded_by: 0112
---

# Patch functions at their definition site, not the import site

Always patch functions at where they are defined, not where they are imported into the module under test.

Example: `@patch('hindsight.retain_safe')` not `@patch('my_module.retain_safe')` when `my_module` imports from `hindsight`.

**Why:** Patching the import site only replaces that module's local reference; all other callers continue using the real function, making the mock ineffective.
