---
id: 0334
topic: architecture
source_issue: 11169
source_phase: plan
created_at: 2026-08-14T19:43:33.955272+00:00
status: active
corroborations: 1
---

# Do not import _-prefixed helpers across module boundaries

Keep helpers like `_resolve_merge_base` local to `scripts/check_console_conformance.py` rather than importing from `scripts/hydraflow_audit/checks/p10_tdd.py`. The `_` prefix signals module-private API.

- If reuse is genuinely needed, promote to a public shared utility or duplicate the logic.
- Do not reach across for `_`-prefixed names.

**Why:** Cross-module `_` imports violate the privacy contract and couple unrelated CI scripts to internal implementation details that may change without notice.
