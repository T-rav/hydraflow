---
id: 2744
topic: testing
source_issue: 11415
source_phase: plan
created_at: 2026-08-18T03:26:10.006541+00:00
status: active
corroborations: 1
---

# Source fake inventory from __all__, not hardcoded lists

The conformance completeness guard in `tests/test_mockworld_fakes_conformance.py` must take its fake inventory from `mockworld.fakes.__all__`.

- Every name in `__all__` must appear in `_FAKE_PAIRS` or in a documented waiver map (currently empty).
- Never mirror the directory listing by hand.

**Why:** A hardcoded list drifts silently when new fakes are added; `__all__` is the authoritative export surface and guarantees new fakes are registered or explicitly waived.
