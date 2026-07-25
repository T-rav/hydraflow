---
id: 0848
topic: gotchas
source_issue: 10509
source_phase: review
created_at: 2026-07-25T09:54:20.029611+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# FakeIssueStore must derive HITL/label-driven fields from label state, not hardcode

When a fake store (e.g. `FakeIssueStore` in `tests/test_fake_issue_store.py`) exposes a field like `_hitl_visited` that in production is derived from label transitions, the fake must compute it from the same label state rather than hardcoding a fixed value.

**Why:** hardcoded fake fields silently diverge from real derivation logic and let bugs in the derivation path pass tests undetected.
