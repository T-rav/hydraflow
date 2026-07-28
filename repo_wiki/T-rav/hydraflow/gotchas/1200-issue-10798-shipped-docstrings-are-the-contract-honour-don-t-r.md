---
id: 1200
topic: gotchas
source_issue: 10798
source_phase: plan
created_at: 2026-07-28T10:05:46.407767+00:00
status: active
corroborations: 1
---

# Shipped docstrings are the contract — honour, don't rewrite, on audit escape

When a docstring (e.g. `factoryStartMs` in `src/ui/src/operator/model/vitals.js` promising "newest still-active session") conflicts with implementation (`.find()` first-match), fix the implementation to match the docstring. Label the issue `audit-upheld` with `detection_source: sampled-audit` and crosslink the escape ledger.

- Flag alternative product semantics (e.g. oldest-active for uptime) in the PR body — out of scope here.
- Do not silently switch semantics under the same API surface.

**Why:** Rewriting the docstring to match the bug hides a product decision inside a bug fix; the audit trail must show the contract was upheld, not redefined.
