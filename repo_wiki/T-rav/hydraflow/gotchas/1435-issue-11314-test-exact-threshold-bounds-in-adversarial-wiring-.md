---
id: 1435
topic: gotchas
source_issue: 11314
source_phase: plan
created_at: 2026-08-16T07:29:20.234653+00:00
status: active
corroborations: 1
---

# Test exact threshold bounds in adversarial wiring tests

When extending `tests/test_plan_phase_adversarial_wiring.py` for boundary fixes, explicitly test the exact valid threshold limit (e.g., `threshold=10` matching `le=10`). Do not rely solely on intermediate values like 0 and 5.

**Why:** Edge case escapes often happen precisely at the valid boundary maximum. Testing only mid-range values leaves the exact threshold unvalidated, allowing fail-closed sentinels to collide with the ceiling.
