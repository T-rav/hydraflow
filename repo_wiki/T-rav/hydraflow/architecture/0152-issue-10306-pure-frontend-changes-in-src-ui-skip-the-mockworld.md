---
id: 0152
topic: architecture
source_issue: 10306
source_phase: plan
created_at: 2026-07-24T03:48:07.536876+00:00
status: active
corroborations: 1
---

# Pure frontend changes in src/ui/ skip the MockWorld tier of the test pyramid

Per `docs/standards/testing/README.md`'s three-layer pyramid (unit + MockWorld scenario + sandbox e2e), a change confined to `src/ui/src/components/` with no orchestrator/runner/Port/subprocess touched has no MockWorld layer to satisfy — state this explicitly in the plan rather than silently omitting it.

Example: the #10306 outcomes-card-grid plan calls MockWorld "N/A: pure frontend change" and relies on Vitest unit/component tests under `src/ui/src/components/__tests__/` as the enforced layer.

**Why:** an unstated skip reads as a missed pyramid layer during review; an explicit N/A with reasoning passes the load-bearing-feature test-layer check.
