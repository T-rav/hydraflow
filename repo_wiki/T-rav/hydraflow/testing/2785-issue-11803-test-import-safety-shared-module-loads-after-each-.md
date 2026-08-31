---
id: 2785
topic: testing
source_issue: 11803
source_phase: plan
created_at: 2026-08-30T09:12:38.105454+00:00
status: active
corroborations: 1
---

# Test import-safety: shared module loads after each phase module

When adding a shared module imported across phases, test that it imports cleanly after each phase's own module is imported first.

Parametrize over `plan_phase_common`, `implement_phase`, `review_phase._flow` — import the phase module, then import `flows.guards`, assert no `ImportError`. This satisfies import-safety artifacts required by prerequisite issue #11802.

**Why:** Circular imports surface only under specific import orderings at runtime, not in a simple standalone import test.
