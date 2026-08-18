---
id: 1494
topic: gotchas
source_issue: 11423
source_phase: plan
created_at: 2026-08-18T04:02:35.358205+00:00
status: stale
corroborations: 1
stale_reason: source issue #11423 closed
---

# _PORT_FAKE_PAIRS sweep catches Port↔Fake kind narrowing repo-wide

When fixing a Port↔Fake signature mismatch, add or extend a registry-wide sweep over `_PORT_FAKE_PAIRS` so the same class of bug cannot recur silently in another pair.

- Import `_PORT_FAKE_PAIRS`, `_named_params`, `_public_methods` from `tests/test_mockworld_fakes_conformance.py`.
- The sweep in `tests/regressions/test_issue_11423.py` asserts zero pairs narrow a positional Port param to keyword-only in the Fake.

**Why:** Without a sweep, the next pair added with the same `*,` mistake passes existing per-method tests but reintroduces the exact MockWorld-only `TypeError`.
