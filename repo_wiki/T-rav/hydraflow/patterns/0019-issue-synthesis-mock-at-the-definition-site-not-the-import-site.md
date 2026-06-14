---
id: 0019
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.315009+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Mock at the definition site, not the import site

Patch `hindsight.tombstone_safe`, not `module_under_test.tombstone_safe`; combine with deferred imports inside test methods.

Example: `@patch('hindsight.tombstone_safe')` not `@patch('mymodule.tombstone_safe')`.

**Why:** Import-site patches fail when the import is deferred or when optional dependencies are conditionally loaded — definition-site patches intercept regardless of import order.
