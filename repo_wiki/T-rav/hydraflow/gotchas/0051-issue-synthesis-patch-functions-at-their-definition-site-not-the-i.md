---
id: 0051
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:11:59.905772+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Patch functions at their definition site, not the import site

Always patch functions at where they are defined, not where they are imported into the module under test.

Example: `@patch('hindsight.retain_safe')` not `@patch('my_module.retain_safe')` when `my_module` imports from `hindsight`.

**Why:** Patching the import site only replaces that module's local reference; all other callers continue using the real function, making the mock ineffective.
