---
id: 0430
topic: architecture
source_issue: 11862
source_phase: plan
created_at: 2026-09-01T03:40:49.615592+00:00
status: active
corroborations: 1
---

# Fail parity tests on unmapped check_id rather than skipping it

Charter drift `check_id` is formatted as `{finding_class}:{target}`. When mapping drift-report findings to policy engine subjects in `tests/architecture/test_policy_charter_parity.py`, any `check_id` that does not map to a decided subject must **fail the test loudly**, never skip. A target containing `:` or a newly added finding class will silently drop out of comparison otherwise.

**Why:** Silent skips turn the parity test into a subset check — it passes even when the engine decides nothing for entire finding classes, defeating the pin's purpose.
