---
id: 2774
topic: testing
source_issue: 11533
source_phase: plan
created_at: 2026-08-21T09:41:01.976097+00:00
status: active
corroborations: 1
---

# Docs/contract-only work skips MockWorld and sandbox layers

Docs and pure-model changes that cross no runtime phase are exempt from the MockWorld scenario and sandbox e2e layers of the three-layer pyramid in `docs/standards/testing/README.md` (the wiki-precedent exemption).
- #11533 ships unit tests plus `tests/regressions/` pins only; the MockWorld and sandbox layers land with #11535/#11537, which actually wire the runtime.
**Why:** Forcing scenario layers onto contract-only diffs produces scaffolding that tests nothing and slows the quality gate; the pyramid binds features that cross a phase boundary.
